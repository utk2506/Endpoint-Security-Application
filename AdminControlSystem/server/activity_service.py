"""
Activity Service — SentraGuard Endpoint User Activity Monitoring
================================================================
Self-contained FastAPI APIRouter for all activity-related endpoints.
Register in app.py with:
    from activity_service import activity_router
    app.include_router(activity_router)

Endpoints:
    POST /api/activity/upload         — Agent uploads batch of events
    GET  /api/activity/events         — Portal: paginated, filtered event list
    PUT  /api/activity/events/{id}    — Portal: edit a single event record
    DELETE /api/activity/events/{id}  — Portal: delete a single event record
    GET  /api/activity/kpi            — Portal: live KPI counts
    GET  /api/activity/analytics      — Portal: all dashboard data (charts, heatmap, timeline)
    GET  /api/activity/summary        — Portal: per-machine / per-user aggregates
    GET  /api/activity/machines       — Portal: distinct machine names
    GET  /api/activity/users          — Portal: distinct usernames
"""

from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, text, case
from sqlalchemy.orm import Session

from models import SessionLocal, ActivityEvent, Device, User

log = logging.getLogger(__name__)

activity_router = APIRouter(prefix="/api/activity", tags=["activity"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Reuse the same JWT auth from app.py via dependency injection patterns.
# We import lazily to avoid circular imports; app.py registers the router
# AFTER setting up get_current_user.

def _get_current_user():
    """Forward-reference import of auth dependency from app module."""
    try:
        from app import get_current_user   # type: ignore
        return get_current_user
    except ImportError:
        # Standalone / test mode — no auth
        async def _noop(request: Request):
            return None
        return _noop


def _require_agent_token():
    """Forward-reference import of agent token check from app module."""
    try:
        from app import require_agent_token  # type: ignore
        return require_agent_token
    except ImportError:
        def _noop(request: Request):
            return None
        return _noop


def _require_admin():
    """Forward-reference import of admin-only dependency from app module."""
    try:
        from app import require_admin  # type: ignore
        return require_admin
    except ImportError:
        async def _noop(request: Request):
            return None
        return _noop

KNOWN_EVENTS = {
    "LOGIN", "LOGOUT", "LOCK", "UNLOCK",
    "IDLE", "ACTIVE", "SCREEN_OFF", "SCREEN_ON",
    "STARTUP", "SHUTDOWN", "APP_USAGE",
}

ACTIVE_STATE_EVENTS = {"LOGIN", "ACTIVE", "UNLOCK", "STARTUP", "SCREEN_ON"}
LOCKED_STATE_EVENTS = {"LOCK", "SCREEN_OFF"}
SESSION_START_EVENTS = {"LOGIN", "STARTUP"}
SESSION_END_EVENTS = {"LOGOUT", "SHUTDOWN"}
EVENT_STATE_MAP = {
    "LOGIN": "active",
    "ACTIVE": "active",
    "UNLOCK": "active",
    "STARTUP": "active",
    "SCREEN_ON": "active",
    "IDLE": "idle",
    "LOCK": "locked",
    "SCREEN_OFF": "locked",
    "LOGOUT": "offline",
    "SHUTDOWN": "offline",
}


def _dt(val) -> Optional[datetime]:
    """Parse ISO date strings into aware datetimes."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        val = str(val).replace("Z", "+00:00")
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _fmt(ev: ActivityEvent) -> dict:
    return {
        "id":            ev.id,
        "device_id":     ev.device_id,
        "timestamp":     _iso(ev.timestamp),
        "event":         ev.event,
        "username":      ev.username or "",
        "machine":       ev.machine or "",
        "serial":        ev.serial or "",
        "ip_address":    ev.ip_address or "",
        "duration":      ev.duration or "—",
        "os_version":    ev.os_version or "",
        "synced":        bool(ev.synced),
        "created_at":    _iso(ev.created_at),
        "process_name":  getattr(ev, "process_name", None) or "",
        "window_title":  getattr(ev, "window_title", None) or "",
        "url":           getattr(ev, "url", None) or "",
        "idle_seconds":  getattr(ev, "idle_seconds", None) or 0,
        "mouse_clicks":  getattr(ev, "mouse_clicks", None) or 0,
        "keypress_count": getattr(ev, "keypress_count", None) or 0,
    }


def _db_dt(val: Optional[datetime]) -> Optional[datetime]:
    if not val:
        return None
    return val if val.tzinfo else val.replace(tzinfo=timezone.utc)


def _normalized_text(value: Optional[str], fallback: str = "Unknown") -> str:
    # Normalize to lowercase — Windows hostnames are case-insensitive and the
    # agent may report "ITSUPPORT" while the device is registered as "itsupport".
    cleaned = (value or "").strip().lower()
    return cleaned or fallback


def _parse_synced_filter(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "synced"}:
        return True
    if lowered in {"false", "0", "no", "pending"}:
        return False
    return None


def _apply_activity_filters(
    q,
    *,
    machine: Optional[str] = None,
    username: Optional[str] = None,
    event_type: Optional[str] = None,
    synced: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
):
    if machine:
        q = q.filter(ActivityEvent.machine == machine)
    if username:
        q = q.filter(ActivityEvent.username == username)
    if event_type:
        q = q.filter(ActivityEvent.event == event_type.upper())

    synced_flag = _parse_synced_filter(synced)
    if synced_flag is not None:
        q = q.filter(ActivityEvent.synced == synced_flag)

    if date_from:
        dt = _dt(date_from)
        if dt:
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            q = q.filter(ActivityEvent.timestamp >= dt_naive)
    if date_to:
        dt = _dt(date_to)
        if dt:
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            q = q.filter(ActivityEvent.timestamp <= dt_naive)

    if search:
        like = f"%{search}%"
        q = q.filter(
            (ActivityEvent.username.ilike(like)) |
            (ActivityEvent.machine.ilike(like)) |
            (ActivityEvent.serial.ilike(like)) |
            (ActivityEvent.ip_address.ilike(like))
        )
    return q


def _event_signature(
    *,
    timestamp: datetime,
    event: str,
    username: Optional[str],
    machine: Optional[str],
    serial: Optional[str],
    ip_address: Optional[str],
    duration: Optional[str],
    os_version: Optional[str],
) -> tuple:
    ts = _db_dt(timestamp)
    return (
        ts.isoformat() if ts else "",
        (event or "").upper(),
        (username or "").strip(),
        (machine or "").strip(),
        (serial or "").strip(),
        (ip_address or "").strip(),
        (duration or "").strip(),
        (os_version or "").strip(),
    )


def _dedupe_events(events: List[ActivityEvent]) -> List[ActivityEvent]:
    deduped: List[ActivityEvent] = []
    seen = set()
    for ev in sorted(events, key=lambda row: ((_db_dt(row.timestamp) or datetime.min.replace(tzinfo=timezone.utc)), row.id)):
        sig = _event_signature(
            timestamp=ev.timestamp,
            event=ev.event,
            username=ev.username,
            machine=ev.machine,
            serial=ev.serial,
            ip_address=ev.ip_address,
            duration=ev.duration,
            os_version=ev.os_version,
        )
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(ev)
    return deduped


def _format_minutes(total_minutes: float) -> str:
    minutes = max(0, int(round(total_minutes)))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _bucket_granularity(range_start: datetime, range_end: datetime) -> str:
    span = max((range_end - range_start).total_seconds(), 0)
    days = span / 86400
    if days <= 2:
        return "hour"
    if days <= 120:
        return "day"
    return "month"


def _floor_bucket(dt: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_bucket(dt: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return dt + timedelta(hours=1)
    if bucket == "day":
        return dt + timedelta(days=1)
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def _bucket_label(dt: datetime, bucket: str) -> str:
    if bucket == "hour":
        return dt.strftime("%H:%M")
    if bucket == "day":
        return dt.strftime("%d %b")
    return dt.strftime("%b %Y")


def _build_segments(
    events: List[ActivityEvent],
    key_getter,
    range_start: datetime,
    range_end: datetime,
) -> tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str]]:
    grouped: Dict[str, List[ActivityEvent]] = defaultdict(list)
    for ev in events:
        grouped[key_getter(ev)].append(ev)

    segments_by_key: Dict[str, List[Dict[str, Any]]] = {}
    latest_state: Dict[str, str] = {}

    for key, rows in grouped.items():
        rows.sort(key=lambda row: ((_db_dt(row.timestamp) or datetime.min.replace(tzinfo=timezone.utc)), row.id))
        current_state: Optional[str] = None
        current_start: Optional[datetime] = None
        segments: List[Dict[str, Any]] = []

        for ev in rows:
            ts = _db_dt(ev.timestamp)
            if not ts:
                continue
            state = EVENT_STATE_MAP.get((ev.event or "").upper())

            if current_state and current_start and ts > current_start:
                end = min(ts, range_end)
                if end > current_start:
                    segments.append({"state": current_state, "start": current_start, "end": end})
                # Always advance current_start so the next event doesn't create
                # an overlapping segment from the same old start time.
                current_start = max(ts, range_start)

            if state is None:
                continue

            latest_state[key] = state
            if state == "offline":
                current_state = None
                current_start = None
                continue

            current_state = state
            if not current_start or ts > current_start:
                current_start = max(ts, range_start)

        if current_state and current_start and range_end > current_start:
            segments.append({"state": current_state, "start": current_start, "end": range_end})
            latest_state[key] = current_state

        segments_by_key[key] = segments

    return segments_by_key, latest_state


def _session_lengths(events: List[ActivityEvent], range_start: datetime, range_end: datetime) -> List[float]:
    grouped: Dict[tuple[str, str], List[ActivityEvent]] = defaultdict(list)
    for ev in events:
        grouped[(_normalized_text(ev.machine), _normalized_text(ev.username))].append(ev)

    durations: List[float] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: ((_db_dt(row.timestamp) or datetime.min.replace(tzinfo=timezone.utc)), row.id))
        session_start: Optional[datetime] = None

        for ev in rows:
            ts = _db_dt(ev.timestamp)
            if not ts:
                continue
            ev_type = (ev.event or "").upper()

            if ev_type in SESSION_START_EVENTS:
                if session_start is None:
                    session_start = max(ts, range_start)
                continue

            if session_start is None and ev_type not in SESSION_END_EVENTS:
                session_start = max(ts, range_start)

            if ev_type in SESSION_END_EVENTS and session_start:
                if ts > session_start:
                    durations.append((ts - session_start).total_seconds() / 60.0)
                session_start = None

        if session_start and range_end > session_start:
            durations.append((range_end - session_start).total_seconds() / 60.0)

    return durations


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ActivityEventIn(BaseModel):
    timestamp: str
    event: str
    username: Optional[str] = None
    machine: Optional[str] = None
    serial: Optional[str] = None
    ip_address: Optional[str] = None
    duration: Optional[str] = None
    os_version: Optional[str] = None
    synced: Optional[bool] = False
    # Application / input tracking fields (APP_USAGE events)
    process_name: Optional[str] = None
    window_title: Optional[str] = None
    url: Optional[str] = None
    idle_seconds: Optional[int] = 0
    mouse_clicks: Optional[int] = 0
    keypress_count: Optional[int] = 0


class ActivityUploadPayload(BaseModel):
    device: Optional[str] = None       # machine hostname
    serial: Optional[str] = None
    events: List[ActivityEventIn]


class ActivityEventEdit(BaseModel):
    timestamp: Optional[str] = None
    event: Optional[str] = None
    username: Optional[str] = None
    machine: Optional[str] = None
    serial: Optional[str] = None
    ip_address: Optional[str] = None
    duration: Optional[str] = None
    os_version: Optional[str] = None
    synced: Optional[bool] = None
    process_name: Optional[str] = None
    window_title: Optional[str] = None
    url: Optional[str] = None
    idle_seconds: Optional[int] = None
    mouse_clicks: Optional[int] = None
    keypress_count: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@activity_router.post("/upload", summary="Agent uploads activity events batch")
def upload_activity(
    payload: ActivityUploadPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Called by SentraGuardSyncService on the endpoint.
    Accepts a batch of activity events and stores them in the database.
    Marks each event as synced=True after storage.
    No auth required beyond the shared agent token (checked in app.py middleware).
    """
    if not payload.events:
        return {"status": "ok", "stored": 0}

    # Attempt to resolve device_id from machine hostname
    machine_name = payload.device or (payload.events[0].machine if payload.events else None)
    device_id: Optional[str] = None
    if machine_name:
        dev = db.query(Device).filter(Device.hostname == machine_name).first()
        if dev:
            device_id = dev.id

    stored = 0
    for ev_in in payload.events:
        ts = _dt(ev_in.timestamp)
        if not ts:
            log.warning("Skipping event with unparseable timestamp: %s", ev_in.timestamp)
            continue

        event_type = (ev_in.event or "").upper()
        if event_type not in KNOWN_EVENTS:
            log.warning("Unknown event type: %s — storing anyway", event_type)

        resolved_machine = (ev_in.machine or payload.device or "").strip() or None
        resolved_serial = (ev_in.serial or payload.serial or "").strip() or None
        resolved_ip = (ev_in.ip_address or "").strip() or None
        resolved_os = (ev_in.os_version or "").strip() or None
        resolved_username = (ev_in.username or "").strip() or None
        resolved_duration = (ev_in.duration or "").strip() or None

        # Resolve per-event device_id if not already set
        ev_device_id = device_id
        if not ev_device_id and resolved_machine:
            dev = db.query(Device).filter(Device.hostname == resolved_machine).first()
            if dev:
                ev_device_id = dev.id

        duplicate = db.query(ActivityEvent.id).filter(
            ActivityEvent.timestamp == ts,
            ActivityEvent.event == event_type,
            ActivityEvent.username == resolved_username,
            ActivityEvent.machine == resolved_machine,
            ActivityEvent.serial == resolved_serial,
            ActivityEvent.ip_address == resolved_ip,
            ActivityEvent.duration == resolved_duration,
            ActivityEvent.os_version == resolved_os,
        ).first()
        if duplicate:
            continue

        try:
            row = ActivityEvent(
                device_id=ev_device_id,
                timestamp=ts,
                event=event_type,
                username=resolved_username,
                machine=resolved_machine,
                serial=resolved_serial,
                ip_address=resolved_ip,
                duration=resolved_duration,
                os_version=resolved_os,
                synced=True,   # it's synced the moment we receive it
                process_name=(ev_in.process_name or "").strip() or None,
                window_title=(ev_in.window_title or "").strip() or None,
                url=(ev_in.url or "").strip() or None,
                idle_seconds=ev_in.idle_seconds or 0,
                mouse_clicks=ev_in.mouse_clicks or 0,
                keypress_count=ev_in.keypress_count or 0,
            )
            db.add(row)
            stored += 1
        except Exception as insert_err:
            log.error("Failed to build ActivityEvent row: %s", insert_err)
            db.rollback()
            continue

    try:
        db.commit()
    except Exception as commit_err:
        log.error("Failed to commit activity events: %s", commit_err)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {commit_err}")

    return {"status": "ok", "stored": stored}


@activity_router.get("/events", summary="Fetch paginated, filtered activity events (supports ?format=csv|xlsx)")
def get_events(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
    # Filters
    machine: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None, alias="event"),
    synced: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    # Pagination
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=10000),
    # Export
    format: Optional[str] = Query(None),   # "csv" | "xlsx"
):
    """Return activity events with optional filters and server-side pagination.
    Pass ?format=csv or ?format=xlsx to download all matching rows as a file."""
    q = _apply_activity_filters(
        db.query(ActivityEvent),
        machine=machine,
        username=username,
        event_type=event_type,
        synced=synced,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    # ── Export: CSV ────────────────────────────────────────────────────────────
    if format == "csv":
        rows = q.order_by(ActivityEvent.timestamp.desc()).limit(limit).all()
        buf = io.StringIO()
        fields = ["id", "timestamp", "event", "username", "machine", "serial",
                  "ip_address", "duration", "os_version", "synced",
                  "process_name", "window_title", "url", "idle_seconds",
                  "mouse_clicks", "keypress_count"]
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for e in rows:
            writer.writerow({
                "id": e.id, "timestamp": _iso(e.timestamp), "event": e.event,
                "username": e.username or "", "machine": e.machine or "",
                "serial": e.serial or "", "ip_address": e.ip_address or "",
                "duration": e.duration or "", "os_version": e.os_version or "",
                "synced": e.synced,
                "process_name": getattr(e, "process_name", "") or "",
                "window_title": getattr(e, "window_title", "") or "",
                "url": getattr(e, "url", "") or "",
                "idle_seconds": getattr(e, "idle_seconds", 0) or 0,
                "mouse_clicks": getattr(e, "mouse_clicks", 0) or 0,
                "keypress_count": getattr(e, "keypress_count", 0) or 0,
            })
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=activity_export.csv"},
        )

    # ── Export: XLSX ───────────────────────────────────────────────────────────
    if format == "xlsx":
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            raise HTTPException(status_code=500, detail="openpyxl not installed — run: pip install openpyxl")

        rows = q.order_by(ActivityEvent.timestamp.desc()).limit(limit).all()
        wb   = openpyxl.Workbook()
        ws   = wb.active
        ws.title = "Activity Events"

        HEADERS = ["ID", "Timestamp", "Event", "Username", "Machine", "Serial",
                   "IP Address", "Duration", "OS Version", "Synced",
                   "Process Name", "Window Title", "URL",
                   "Idle Seconds", "Mouse Clicks", "Key Presses"]
        hdr_fill = PatternFill("solid", fgColor="0D1620")
        hdr_font = Font(bold=True, color="00E5FF")

        for col_i, hdr in enumerate(HEADERS, 1):
            cell = ws.cell(row=1, column=col_i, value=hdr)
            cell.font      = hdr_font
            cell.fill      = hdr_fill
            cell.alignment = Alignment(horizontal="center")

        for row_i, e in enumerate(rows, 2):
            ws.cell(row=row_i, column=1,  value=e.id)
            ws.cell(row=row_i, column=2,  value=_iso(e.timestamp))
            ws.cell(row=row_i, column=3,  value=e.event)
            ws.cell(row=row_i, column=4,  value=e.username or "")
            ws.cell(row=row_i, column=5,  value=e.machine or "")
            ws.cell(row=row_i, column=6,  value=e.serial or "")
            ws.cell(row=row_i, column=7,  value=e.ip_address or "")
            ws.cell(row=row_i, column=8,  value=e.duration or "")
            ws.cell(row=row_i, column=9,  value=e.os_version or "")
            ws.cell(row=row_i, column=10, value="Yes" if e.synced else "No")
            ws.cell(row=row_i, column=11, value=getattr(e, "process_name", "") or "")
            ws.cell(row=row_i, column=12, value=getattr(e, "window_title", "") or "")
            ws.cell(row=row_i, column=13, value=getattr(e, "url", "") or "")
            ws.cell(row=row_i, column=14, value=getattr(e, "idle_seconds", 0) or 0)
            ws.cell(row=row_i, column=15, value=getattr(e, "mouse_clicks", 0) or 0)
            ws.cell(row=row_i, column=16, value=getattr(e, "keypress_count", 0) or 0)

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 20

        xlsx_buf = io.BytesIO()
        wb.save(xlsx_buf)
        xlsx_buf.seek(0)
        return StreamingResponse(
            iter([xlsx_buf.read()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=activity_export.xlsx"},
        )

    # ── Normal JSON response ───────────────────────────────────────────────────
    total  = q.count()
    events = (
        q.order_by(ActivityEvent.timestamp.desc())
         .offset((page - 1) * limit)
         .limit(limit)
         .all()
    )

    return {
        "total":  total,
        "page":   page,
        "limit":  limit,
        "pages":  max(1, (total + limit - 1) // limit),
        "events": [_fmt(e) for e in events],
    }



@activity_router.put("/events/{event_id}", summary="Edit an activity event record")
def edit_event(
    event_id: int,
    body: ActivityEventEdit,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin()),
):
    """Update editable fields on a single activity event. Requires admin auth."""
    row = db.query(ActivityEvent).filter(ActivityEvent.id == event_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Activity event not found")

    if body.timestamp is not None:
        dt = _dt(body.timestamp)
        if dt:
            row.timestamp = dt
    if body.event is not None:
        row.event = body.event.upper()
    if body.username is not None:
        row.username = body.username
    if body.machine is not None:
        row.machine = body.machine
    if body.serial is not None:
        row.serial = body.serial
    if body.ip_address is not None:
        row.ip_address = body.ip_address
    if body.duration is not None:
        row.duration = body.duration
    if body.os_version is not None:
        row.os_version = body.os_version
    if body.synced is not None:
        row.synced = body.synced

    db.commit()
    db.refresh(row)
    return _fmt(row)


@activity_router.delete("/events/{event_id}", summary="Delete an activity event record")
def delete_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin()),
):
    """Permanently remove a single activity event. Requires admin auth."""
    row = db.query(ActivityEvent).filter(ActivityEvent.id == event_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Activity event not found")
    db.delete(row)
    db.commit()
    return {"status": "ok", "deleted": event_id}


@activity_router.get("/kpi", summary="Live KPI counts for dashboard cards")
def get_kpi(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
    window_minutes: int = Query(30, description="Look-back window in minutes for 'active' status"),
):
    """
    Returns counts for the four KPI dashboard cards.
    'Active'  = machines that had an ACTIVE or LOGIN event in the last N minutes.
    'Idle'    = machines whose last event was IDLE (and no ACTIVE since).
    'Locked'  = machines whose last event was LOCK (and no UNLOCK since).
    'Offline' = registered devices with no activity event in the last 30 minutes.
    """
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(minutes=window_minutes)).replace(tzinfo=None)

    # Machines with any recent event (last N minutes)
    recent_q = (
        db.query(ActivityEvent.machine)
          .filter(ActivityEvent.timestamp >= window_start)
          .distinct()
    )
    # Normalize to lowercase so "ITSUPPORT" and "itsupport" are treated as one machine
    recent_machines = {r.machine.strip().lower() for r in recent_q if r.machine}

    # Latest event per machine
    subq = (
        db.query(
            ActivityEvent.machine,
            func.max(ActivityEvent.timestamp).label("max_ts"),
        )
        .group_by(ActivityEvent.machine)
        .subquery()
    )
    latest_rows = (
        db.query(ActivityEvent)
          .join(subq, (ActivityEvent.machine == subq.c.machine) &
                      (ActivityEvent.timestamp == subq.c.max_ts))
          .all()
    )

    active_count  = 0
    idle_count    = 0
    locked_count  = 0

    # Use a set to avoid double-counting the same physical machine under two
    # different cases (e.g., "itsupport" vs "ITSUPPORT")
    counted_machines: set = set()
    for row in latest_rows:
        key = (row.machine or "").strip().lower()
        if key in counted_machines:
            continue
        counted_machines.add(key)
        if row.event in ("ACTIVE", "LOGIN", "UNLOCK", "STARTUP", "SCREEN_ON"):
            active_count += 1
        elif row.event == "IDLE":
            idle_count += 1
        elif row.event == "LOCK":
            locked_count += 1

    # Offline = registered devices with no activity in the window
    registered_hostnames = {
        (d.hostname or "").strip().lower()
        for d in db.query(Device).filter(Device.is_uninstalled == False).all()
        if (d.hostname or "").strip()
    }
    total_registered = len(registered_hostnames)
    offline_count = max(0, total_registered - len(recent_machines & registered_hostnames))

    # Total events
    total_events = db.query(ActivityEvent).count()

    # Pending = events received but marked synced=False (edge case / local only)
    pending_count = db.query(ActivityEvent).filter(ActivityEvent.synced == False).count()

    return {
        "active":           active_count,
        "idle":             idle_count,
        "locked":           locked_count,
        "offline":          offline_count,
        "total_events":     total_events,
        "pending_count":    pending_count,
        "total_registered": total_registered,
    }


@activity_router.get("/summary", summary="Per-machine and per-user event aggregates")
def get_summary(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Aggregated event counts per machine and per user for charts."""
    q = _apply_activity_filters(
        db.query(ActivityEvent),
        date_from=date_from,
        date_to=date_to,
    )

    # Per-machine active time proxy: count ACTIVE events
    by_machine = (
        q.with_entities(
            ActivityEvent.machine,
            func.count(ActivityEvent.id).label("total"),
            func.sum(
                case((ActivityEvent.event == "ACTIVE", 1), else_=0)
            ).label("active_count"),
        )
        .group_by(ActivityEvent.machine)
        .order_by(func.count(ActivityEvent.id).desc())
        .limit(20)
        .all()
    )

    # Per-user event counts
    by_user = (
        q.with_entities(
            ActivityEvent.username,
            func.count(ActivityEvent.id).label("total"),
        )
        .group_by(ActivityEvent.username)
        .order_by(func.count(ActivityEvent.id).desc())
        .limit(20)
        .all()
    )

    # Hourly distribution for heatmap (hour → count)
    # SQLite: strftime('%H', timestamp)
    hourly = (
        q.with_entities(
            func.strftime("%H", ActivityEvent.timestamp).label("hour"),
            func.count(ActivityEvent.id).label("count"),
        )
        .group_by(text("hour"))
        .all()
    )

    return {
        "by_machine": [
            {"machine": r.machine or "unknown", "total": r.total}
            for r in by_machine
        ],
        "by_user": [
            {"username": r.username or "unknown", "total": r.total}
            for r in by_user
        ],
        "hourly": {
            (r.hour or "00"): r.count for r in hourly
        },
    }


@activity_router.get("/analytics", summary="Filter-aware activity analytics for the dashboard")
def get_analytics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
    machine: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None, alias="event"),
    synced: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    q = _apply_activity_filters(
        db.query(ActivityEvent),
        machine=machine,
        username=username,
        event_type=event_type,
        synced=synced,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    raw_events = q.order_by(ActivityEvent.timestamp.asc(), ActivityEvent.id.asc()).all()
    events = _dedupe_events(raw_events)

    now = datetime.now(timezone.utc)
    range_start = _db_dt(_dt(date_from)) if date_from else None
    range_end = _db_dt(_dt(date_to)) if date_to and _dt(date_to) else None
    if range_start is None:
        range_start = _db_dt(events[0].timestamp) if events else now - timedelta(days=1)
    if range_end is None:
        range_end = now
    range_start = _db_dt(range_start) or now - timedelta(days=1)
    range_end = _db_dt(range_end) or now
    if range_end <= range_start:
        range_end = range_start + timedelta(hours=1)

    try:
        registered_machines = {
            d.hostname.strip().lower()   # normalize: hostnames are case-insensitive
            for d in db.query(Device).filter(Device.is_uninstalled == False).all()
            if (d.hostname or "").strip()
        }
    except Exception as e:
        log.error("get_analytics: failed to query registered devices: %s", e)
        registered_machines = set()

    event_machine_names = {_normalized_text(ev.machine) for ev in events}
    narrow_machine_scope = bool(username or event_type or search or _parse_synced_filter(synced) is not None)
    if machine:
        candidate_machines = {machine}
    elif narrow_machine_scope:
        candidate_machines = set(event_machine_names)
    else:
        candidate_machines = set(registered_machines) | {m for m in event_machine_names if m != "Unknown"}
    if "Unknown" in event_machine_names:
        candidate_machines.add("Unknown")

    machine_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "total_events": 0,
        "active_minutes": 0.0,
        "hours": [0] * 24,
    })
    user_event_counts: Dict[str, int] = defaultdict(int)
    for ev in events:
        machine_name = _normalized_text(ev.machine)
        username_value = _normalized_text(ev.username)
        machine_stats[machine_name]["total_events"] += 1
        user_event_counts[username_value] += 1
        ts = _db_dt(ev.timestamp)
        if ts:
            machine_stats[machine_name]["hours"][ts.hour] += 1

    machine_segments, latest_machine_state = _build_segments(
        events,
        lambda ev: _normalized_text(ev.machine),
        range_start,
        range_end,
    )
    user_segments, _ = _build_segments(
        events,
        lambda ev: _normalized_text(ev.username),
        range_start,
        range_end,
    )

    for machine_name, segments in machine_segments.items():
        for seg in segments:
            if seg["state"] == "active":
                machine_stats[machine_name]["active_minutes"] += (
                    (seg["end"] - seg["start"]).total_seconds() / 60.0
                )

    active_count = 0
    idle_count = 0
    locked_count = 0
    offline_machines = set()
    for machine_name in candidate_machines:
        state_name = latest_machine_state.get(machine_name)
        if state_name == "active":
            active_count += 1
        elif state_name == "idle":
            idle_count += 1
        elif state_name == "locked":
            locked_count += 1
        else:
            offline_machines.add(machine_name)

    total_events = len(events)
    pending_count = sum(1 for ev in events if not ev.synced)
    sync_health = 100 if total_events == 0 else round(((total_events - pending_count) / total_events) * 100)

    bucket = _bucket_granularity(range_start, range_end)
    bucket_cursor = _floor_bucket(range_start, bucket)
    buckets: List[tuple[datetime, datetime]] = []
    labels: List[str] = []
    while bucket_cursor < range_end:
        next_cursor = _next_bucket(bucket_cursor, bucket)
        buckets.append((bucket_cursor, next_cursor))
        labels.append(_bucket_label(bucket_cursor, bucket))
        bucket_cursor = next_cursor

    active_series: List[int] = []
    idle_series: List[int] = []
    locked_series: List[int] = []
    offline_series: List[int] = []

    for bucket_start, bucket_end in buckets:
        bucket_active = 0
        bucket_idle = 0
        bucket_locked = 0
        bucket_offline = 0
        for machine_name in candidate_machines:
            current_state = None
            for seg in machine_segments.get(machine_name, []):
                if seg["start"] < bucket_end and seg["end"] > bucket_start:
                    current_state = seg["state"]
            if current_state == "active":
                bucket_active += 1
            elif current_state == "idle":
                bucket_idle += 1
            elif current_state == "locked":
                bucket_locked += 1
            else:
                bucket_offline += 1

        active_series.append(bucket_active)
        idle_series.append(bucket_idle)
        locked_series.append(bucket_locked)
        offline_series.append(bucket_offline)

    top_machine_rows = sorted(
        (
            {
                "machine": machine_name,
                "active_minutes": round(stats["active_minutes"], 1),
                "active_label": _format_minutes(stats["active_minutes"]),
                "total_events": stats["total_events"],
            }
            for machine_name, stats in machine_stats.items()
        ),
        key=lambda row: (-row["active_minutes"], -row["total_events"], row["machine"]),
    )

    heatmap_rows = []
    heatmap_names = [row["machine"] for row in top_machine_rows[:6]]
    if not heatmap_names and candidate_machines:
        heatmap_names = sorted(candidate_machines)[:6]
    for machine_name in heatmap_names:
        heatmap_rows.append({
            "machine": machine_name,
            "counts": machine_stats[machine_name]["hours"],
        })

    session_lengths = _session_lengths(events, range_start, range_end)
    session_bucket_defs = [
        ("<1h", 0, 60),
        ("1-2h", 60, 120),
        ("2-4h", 120, 240),
        ("4-6h", 240, 360),
        ("6-8h", 360, 480),
        ("8-10h", 480, 600),
        (">10h", 600, None),
    ]
    session_buckets = []
    for label, lower, upper in session_bucket_defs:
        count = 0
        for minutes in session_lengths:
            if minutes < lower:
                continue
            if upper is None or minutes < upper:
                count += 1
        session_buckets.append({"label": label, "count": count})

    user_rankings = sorted(
        user_segments.items(),
        key=lambda item: (
            -sum((seg["end"] - seg["start"]).total_seconds() for seg in item[1]),
            -user_event_counts[item[0]],
            item[0],
        ),
    )[:6]

    span_seconds = max((range_end - range_start).total_seconds(), 1)
    tick_total = 6 if bucket in {"day", "month"} else 11
    timeline_ticks = []
    for idx in range(tick_total):
        ratio = 0 if tick_total == 1 else idx / (tick_total - 1)
        tick_dt = range_start + timedelta(seconds=span_seconds * ratio)
        tick_label = tick_dt.strftime("%d %b") if bucket in {"day", "month"} else tick_dt.strftime("%H")
        timeline_ticks.append({"label": tick_label, "offset": round(ratio * 100, 2)})

    timeline_users = []
    for username_value, segments in user_rankings:
        timeline_users.append({
            "username": username_value,
            "segments": [
                {
                    "state": seg["state"],
                    "start": _iso(seg["start"]),
                    "end": _iso(seg["end"]),
                }
                for seg in segments
            ],
        })

    return {
        "range": {
            "from": _iso(range_start),
            "to": _iso(range_end),
        },
        "kpis": {
            "active": active_count,
            "idle": idle_count,
            "locked": locked_count,
            "offline": len(offline_machines),
            "total_events": total_events,
            "pending_count": pending_count,
            "sync_health": sync_health,
        },
        "hourly_series": {
            "bucket": bucket,
            "labels": labels,
            "active": active_series,
            "idle": idle_series,
            "locked": locked_series,
            "offline": offline_series,
        },
        "top_machines": top_machine_rows[:7],
        "session_stats": {
            "avg_minutes": round((sum(session_lengths) / len(session_lengths)), 1) if session_lengths else 0,
            "avg_label": _format_minutes(sum(session_lengths) / len(session_lengths)) if session_lengths else "0m",
            "longest_minutes": round(max(session_lengths), 1) if session_lengths else 0,
            "longest_label": _format_minutes(max(session_lengths)) if session_lengths else "0m",
            "total_sessions": len(session_lengths),
            "buckets": session_buckets,
        },
        "heatmap": {
            "hours": [f"{hour:02d}" for hour in range(24)],
            "rows": heatmap_rows,
        },
        "timeline": {
            "range_start": _iso(range_start),
            "range_end": _iso(range_end),
            "ticks": timeline_ticks,
            "users": timeline_users,
        },
    }


@activity_router.get("/machines", summary="Distinct machine names in activity log")
def get_machines(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
):
    names = {
        (row.machine or "").strip()
        for row in (
            db.query(ActivityEvent.machine)
              .filter(ActivityEvent.machine != None)
              .distinct()
              .all()
        )
        if (row.machine or "").strip()
    }
    names.update(
        (row.hostname or "").strip()
        for row in db.query(Device.hostname).filter(Device.is_uninstalled == False).all()
        if (row.hostname or "").strip()
    )
    return {"machines": sorted(names)}


@activity_router.get("/users", summary="Distinct usernames in activity log")
def get_users(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
):
    users = {
        (row.username or "").strip()
        for row in (
            db.query(ActivityEvent.username)
              .filter(ActivityEvent.username != None)
              .distinct()
              .all()
        )
        if (row.username or "").strip()
    }
    return {"users": sorted(users)}


@activity_router.get("/processes", summary="Distinct process names from APP_USAGE events")
def get_processes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
):
    """Returns distinct process names for the Application filter dropdown."""
    rows = (
        db.query(ActivityEvent.process_name)
          .filter(ActivityEvent.event == "APP_USAGE")
          .filter(ActivityEvent.process_name != None)
          .distinct()
          .all()
    )
    names = sorted({(r.process_name or "").strip() for r in rows if (r.process_name or "").strip()})
    return {"processes": names}


@activity_router.get("/app-usage", summary="Application usage breakdown and productivity analytics")
def get_app_usage(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user()),
    machine: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """
    Returns three datasets for new dashboard charts:
    - app_breakdown: top 8 apps by total sampled seconds (each APP_USAGE row = 30s)
    - productivity_by_user: per-user active/idle/lock minutes + productivity score
    - login_distribution: 24-element array of login counts by hour of day
    """
    q = _apply_activity_filters(
        db.query(ActivityEvent),
        machine=machine,
        username=username,
        date_from=date_from,
        date_to=date_to,
    )
    all_events = q.order_by(ActivityEvent.timestamp.asc(), ActivityEvent.id.asc()).all()
    events = _dedupe_events(all_events)

    # ── 1. App breakdown ──────────────────────────────────────────────────────
    APP_SAMPLE_SECS = 30   # each APP_USAGE row represents 30 seconds of tracking
    app_seconds: Dict[str, int] = defaultdict(int)
    for ev in events:
        if (ev.event or "").upper() == "APP_USAGE" and ev.process_name:
            app_seconds[ev.process_name.strip()] += APP_SAMPLE_SECS

    total_app_secs = sum(app_seconds.values()) or 1
    sorted_apps = sorted(app_seconds.items(), key=lambda x: -x[1])

    # Top 8, bundle rest as "Other"
    top_apps = sorted_apps[:8]
    other_secs = sum(v for _, v in sorted_apps[8:])

    app_breakdown = [
        {
            "process_name": name,
            "total_seconds": secs,
            "pct": round((secs / total_app_secs) * 100, 1),
        }
        for name, secs in top_apps
    ]
    if other_secs:
        app_breakdown.append({
            "process_name": "Other",
            "total_seconds": other_secs,
            "pct": round((other_secs / total_app_secs) * 100, 1),
        })

    # ── 2. Productivity per user ──────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    range_start = _db_dt(_dt(date_from)) if date_from else None
    range_end   = _db_dt(_dt(date_to))   if date_to and _dt(date_to) else None
    if range_start is None:
        range_start = _db_dt(events[0].timestamp) if events else now - timedelta(days=1)
    if range_end is None:
        range_end = now
    range_start = _db_dt(range_start) or now - timedelta(days=1)
    range_end   = _db_dt(range_end)   or now
    if range_end <= range_start:
        range_end = range_start + timedelta(hours=1)

    user_segments, _ = _build_segments(
        events,
        lambda ev: _normalized_text(ev.username),
        range_start,
        range_end,
    )

    productivity_by_user: List[Dict[str, Any]] = []
    for uname, segments in user_segments.items():
        active_secs = idle_secs = lock_secs = 0.0
        for seg in segments:
            dur = (seg["end"] - seg["start"]).total_seconds()
            if seg["state"] == "active":
                active_secs += dur
            elif seg["state"] == "idle":
                idle_secs += dur
            elif seg["state"] == "locked":
                lock_secs += dur
        total_secs = active_secs + idle_secs + lock_secs or 1
        score = round((active_secs / total_secs) * 100, 1)
        productivity_by_user.append({
            "username":       uname,
            "active_mins":    round(active_secs / 60, 1),
            "idle_mins":      round(idle_secs / 60, 1),
            "lock_mins":      round(lock_secs / 60, 1),
            "productivity_score": score,
        })

    # Sort by active minutes descending, cap at top 10
    productivity_by_user.sort(key=lambda x: -x["active_mins"])
    productivity_by_user = productivity_by_user[:10]

    # ── 3. Login distribution (count per hour of day) ─────────────────────────
    login_dist: List[int] = [0] * 24
    for ev in events:
        if (ev.event or "").upper() == "LOGIN":
            ts = _db_dt(ev.timestamp)
            if ts:
                login_dist[ts.hour] += 1

    return {
        "app_breakdown":       app_breakdown,
        "productivity_by_user": productivity_by_user,
        "login_distribution":  login_dist,
    }


