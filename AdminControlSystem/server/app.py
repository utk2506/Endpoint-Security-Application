"""
Admin Control System — Central Server
FastAPI application serving REST API + static portal files.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore
from fastapi.responses import FileResponse  # type: ignore
from pydantic import BaseModel  # type: ignore
from sqlalchemy.orm import Session  # type: ignore

from models import SessionLocal, Device, Command, AdminSnapshot, EventLog  # type: ignore

# ── WebSocket Manager for Real-Time Terminal ───────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # Maps device_id -> {"agent": WebSocket, "portal": WebSocket}
        self.active_connections: Dict[str, Dict[str, Optional[WebSocket]]] = {}

    async def connect(self, device_id: str, client_type: str, websocket: WebSocket):
        await websocket.accept()
        if device_id not in self.active_connections:
            self.active_connections[device_id] = {"agent": None, "portal": None}
        self.active_connections[device_id][client_type] = websocket

    def disconnect(self, device_id: str, client_type: str):
        if device_id in self.active_connections:
            self.active_connections[device_id][client_type] = None
            if not self.active_connections[device_id]["agent"] and not self.active_connections[device_id]["portal"]:
                del self.active_connections[device_id]  # type: ignore[misc]

    async def forward(self, device_id: str, source_type: str, message: str):
        target_type = "portal" if source_type == "agent" else "agent"
        if device_id in self.active_connections:
            target_ws = self.active_connections[device_id].get(target_type)
            if target_ws:
                try:
                    await target_ws.send_text(message)
                except Exception:
                    pass

manager = ConnectionManager()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Admin Control System", version="1.0.0")

# CORS middleware removed to avoid WebSocket 403s


# ── WebSocket Endpoints ──────────────────────────────────────────────────────

@app.websocket("/ws/portal/{device_id}")
async def websocket_portal(websocket: WebSocket, device_id: str):
    await manager.connect(device_id, "portal", websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.forward(device_id, "portal", data)
    except WebSocketDisconnect:
        manager.disconnect(device_id, "portal")


@app.websocket("/ws/agent/{device_id}")
async def websocket_agent(websocket: WebSocket, device_id: str):
    await manager.connect(device_id, "agent", websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.forward(device_id, "agent", data)
    except WebSocketDisconnect:
        manager.disconnect(device_id, "agent")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic schemas ────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    hostname: str
    ip_address: str
    system_info: Optional[dict] = None
    all_users: Optional[list[dict]] = None


class SendCommandRequest(BaseModel):
    device_id: str
    action: str          # grant | revoke | check | shell
    username: Optional[str] = None
    payload: Optional[str] = None
    expires_at: Optional[str] = None   # ISO-8601 UTC string, e.g. "2026-03-14T18:30:00Z"


class CommandResultRequest(BaseModel):
    command_id: int
    status: str          # completed | failed
    result: Optional[str] = None
    admin_list: Optional[list[str]] = None   # populated for 'check' actions


# ── API: Device Management ──────────────────────────────────────────────────

@app.post("/register")
def register_device(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new device or update last_seen for an existing one."""
    sys_info_str = json.dumps(req.system_info) if req.system_info else None
    all_users_str = json.dumps(req.all_users) if req.all_users else None

    device = db.query(Device).filter(Device.hostname == req.hostname).first()
    if device:
        device.ip_address = req.ip_address
        device.last_seen = datetime.now(timezone.utc)
        if sys_info_str:
            device.system_info = sys_info_str
        if all_users_str:
            device.all_users = all_users_str
        db.commit()
        db.refresh(device)
        return {"message": "Device updated", "device_id": device.id}

    device = Device(hostname=req.hostname, ip_address=req.ip_address, system_info=sys_info_str, all_users=all_users_str)
    db.add(device)
    db.commit()
    db.refresh(device)
    return {"message": "Device registered", "device_id": device.id}


@app.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """Return all registered devices."""
    devices = db.query(Device).order_by(Device.hostname).all()

    def parse_sys_info(s):
        if not s: return None
        try: return json.loads(s)
        except: return None

    return [
        {
            "id": d.id,
            "hostname": d.hostname,
            "ip_address": d.ip_address,
            "registered_at": d.registered_at.isoformat(timespec='milliseconds') + "Z" if d.registered_at else None,
            "last_seen": d.last_seen.isoformat(timespec='milliseconds') + "Z" if d.last_seen else None,
            "system_info": parse_sys_info(d.system_info),
            "all_users": parse_sys_info(d.all_users),
        }
        for d in devices
    ]


# ── API: Command Queue ─────────────────────────────────────────────────────

@app.post("/send_command")
def send_command(req: SendCommandRequest, db: Session = Depends(get_db)):
    """Queue a command for a device."""
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

<<<<<<< HEAD
    if req.action not in ("grant", "revoke", "check", "shell", "create_user", "notify"):
        raise HTTPException(status_code=400, detail="Action must be grant, revoke, check, shell, create_user, or notify")
=======
    if req.action not in ("grant", "revoke", "check", "shell", "create_user"):
        raise HTTPException(status_code=400, detail="Action must be grant, revoke, check, shell, or create_user")
>>>>>>> origin/development

    if req.action in ("grant", "revoke", "create_user") and not req.username:
        raise HTTPException(status_code=400, detail="Username required for grant/revoke/create_user")

    if req.action in ("shell", "create_user") and not req.payload:
        raise HTTPException(status_code=400, detail="Payload (script or password) required for this command type")

    # Parse optional expiry time
    expires_at_dt = None
    if req.expires_at:
        try:
            expires_at_dt = datetime.fromisoformat(req.expires_at.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format. Use ISO-8601 e.g. 2026-03-14T18:30:00Z")

    cmd = Command(
        device_id=req.device_id,
        action=req.action,
        username=req.username,
        payload=req.payload,
        expires_at=expires_at_dt,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return {"message": "Command queued", "command_id": cmd.id}


@app.get("/get_command/{device_id}")
def get_command(device_id: str, db: Session = Depends(get_db)):
    """Agent polls: return the oldest pending command for a device."""
    
    # Heartbeat: update last_seen
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        device.last_seen = datetime.now(timezone.utc)
        db.commit()

    cmd = (
        db.query(Command)
        .filter(Command.device_id == device_id, Command.status == "pending")
        .order_by(Command.created_at)
        .first()
    )
    if not cmd:
        return {"command": None}

    # Mark as executing so it isn't returned again
    cmd.status = "executing"
    db.commit()
    db.refresh(cmd)

    return {
        "command": {
            "id": cmd.id,
            "action": cmd.action,
            "username": cmd.username,
            "payload": cmd.payload,
        }
    }


@app.post("/command_result")
def command_result(req: CommandResultRequest, db: Session = Depends(get_db)):
    """Agent reports the result of a command execution."""
    cmd = db.query(Command).filter(Command.id == req.command_id).first()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    cmd.status = req.status
    cmd.result = req.result
    cmd.executed_at = datetime.now(timezone.utc)
    
    # Heartbeat: update last_seen
    device = db.query(Device).filter(Device.id == cmd.device_id).first()
    if device:
        device.last_seen = datetime.now(timezone.utc)
        
    db.commit()

    # If the agent sent back an admin list (from a 'check' action), save it
    if req.admin_list is not None:
        snapshot = AdminSnapshot(
            device_id=cmd.device_id,
            admin_users=json.dumps(req.admin_list),
        )
        db.add(snapshot)
        db.commit()

    return {"message": "Result recorded"}


# ── API: Admin List ─────────────────────────────────────────────────────────

@app.get("/admin_list/{device_id}")
def get_admin_list(device_id: str, db: Session = Depends(get_db)):
    """Return the latest admin snapshot for a device."""
    snapshot = (
        db.query(AdminSnapshot)
        .filter(AdminSnapshot.device_id == device_id)
        .order_by(AdminSnapshot.captured_at.desc())
        .first()
    )
    if not snapshot:
        return {"admin_users": [], "captured_at": None}

    return {
        "admin_users": json.loads(snapshot.admin_users),
        "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
    }


# ── API: Command History ────────────────────────────────────────────────────

@app.get("/commands/history")
def command_history(
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    device_id: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return recent command history across devices, with filtering, pagination, and sorting."""
    query = db.query(Command)

    if device_id:
        query = query.filter(Command.device_id == device_id)
    if action:
        query = query.filter(Command.action == action)
    if status:
        query = query.filter(Command.status == status)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (Command.username.ilike(search_pattern)) |
            (Command.result.ilike(search_pattern)) |
            (Command.payload.ilike(search_pattern))
        )

    # Calculate total matching results before limit/offset
    total_count = query.count()

    # Apply sorting
    sort_col = getattr(Command, sort_by, None)
    if sort_col is None:
        sort_col = Command.created_at
        
    if sort_dir.lower() == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    # Apply pagination
    offset = (page - 1) * limit
    cmds = query.offset(offset).limit(limit).all()

    results = []
    for c in cmds:
        device = db.query(Device).filter(Device.id == c.device_id).first()
        results.append({
            "id": c.id,
            "device_id": c.device_id,
            "device_hostname": device.hostname if device else "Unknown",
            "action": c.action,
            "username": c.username,
            "payload": "***" if c.action == "create_user" else c.payload,
            "status": c.status,
            "result": c.result,
            "created_at": c.created_at.isoformat(timespec='milliseconds') + "Z" if c.created_at else None,
            "executed_at": c.executed_at.isoformat(timespec='milliseconds') + "Z" if c.executed_at else None,
            "expires_at": c.expires_at.isoformat(timespec='milliseconds') + "Z" if c.expires_at else None,
            "auto_revoked": c.auto_revoked or False,
        })
        
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "commands": results
    }


# ── API: Event Log Monitoring ───────────────────────────────────────────────

class EventLogEntry(BaseModel):
    event_id: int
    event_name: str
    log_source: str
    timestamp: str
    username: Optional[str] = None
    hostname: Optional[str] = None
    message: Optional[str] = None

class DeviceLogsPayload(BaseModel):
    device_id: str
    logs: list[EventLogEntry]

@app.post("/api/v1/device/logs")
def ingest_device_logs(payload: DeviceLogsPayload, db: Session = Depends(get_db)):
    """Receive batched event logs from an agent."""
    device = db.query(Device).filter(Device.id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    inserted = 0
    for entry in payload.logs:
        try:
            ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)

        log_row = EventLog(
            device_id=payload.device_id,
            hostname=entry.hostname or device.hostname,
            username=entry.username,
            event_id=entry.event_id,
            event_name=entry.event_name,
            log_source=entry.log_source,
            timestamp=ts,
            message=entry.message,
        )
        db.add(log_row)
        inserted += 1

    db.commit()
    return {"status": "ok", "inserted": inserted}


@app.get("/api/v1/event-logs")
def get_event_logs(
    page: int = 1,
    limit: int = 20,
    sort_by: str = "timestamp",
    sort_dir: str = "desc",
    device_id: Optional[str] = None,
    log_source: Optional[str] = None,
    event_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return paginated, filterable, sortable event logs for the portal."""
    query = db.query(EventLog)

    if device_id:
        query = query.filter(EventLog.device_id == device_id)
    if log_source:
        query = query.filter(EventLog.log_source == log_source)
    if event_id:
        query = query.filter(EventLog.event_id == event_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (EventLog.username.ilike(pattern)) |
            (EventLog.message.ilike(pattern)) |
            (EventLog.event_name.ilike(pattern))
        )

    total_count = query.count()

    # Apply sorting
    sort_col = getattr(EventLog, sort_by, None)
    if sort_col is None:
        sort_col = EventLog.timestamp
    if sort_dir.lower() == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    # Apply pagination
    offset = (page - 1) * limit
    logs = query.offset(offset).limit(limit).all()

    results = []
    for log_entry in logs:
        device = db.query(Device).filter(Device.id == log_entry.device_id).first()
        results.append({
            "id": log_entry.id,
            "device_id": log_entry.device_id,
            "hostname": log_entry.hostname or (device.hostname if device else "Unknown"),
            "username": log_entry.username,
            "event_id": log_entry.event_id,
            "event_name": log_entry.event_name,
            "log_source": log_entry.log_source,
            "timestamp": log_entry.timestamp.isoformat(timespec='milliseconds') + "Z" if log_entry.timestamp else None,
            "message": log_entry.message,
            "created_at": log_entry.created_at.isoformat(timespec='milliseconds') + "Z" if log_entry.created_at else None,
        })

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "logs": results
    }


@app.get("/api/v1/event-logs/summary")
def get_event_log_summary(
    device_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return aggregated event log counts for dashboard stats cards."""
    from sqlalchemy import func  # type: ignore

    query = db.query(EventLog.event_name, func.count(EventLog.id).label("count"))

    if device_id:
        query = query.filter(EventLog.device_id == device_id)

    rows = query.group_by(EventLog.event_name).all()

    summary = {}
    for event_name, count in rows:
        summary[event_name] = count

    # Calculate category totals
    login_events = {
        "login_success", "login_failed", "logon_explicit_creds",
        "ntlm_auth", "kerberos_ticket_req", "kerberos_service_req", 
        "kerberos_ticket_renew", "kerberos_preauth_failed"
    }
    logoff_events = {"logoff", "user_logoff"}
    crash_events = {"app_crash", "app_hang", "error_reporting"}
    privilege_events = {
        "priv_use", "priv_service_op", "user_added_to_group", "user_added_to_priv_group",
        "special_privs_assigned", "priv_service_call", "priv_obj_access", "special_groups_assigned"
    }

    return {
        "total_events": sum(summary.values()),
        "logins": sum(summary.get(e, 0) for e in login_events),
        "logoffs": sum(summary.get(e, 0) for e in logoff_events),
        "crashes": sum(summary.get(e, 0) for e in crash_events),
        "privilege_events": sum(summary.get(e, 0) for e in privilege_events),
        "by_event_name": summary
    }


<<<<<<< HEAD
# ── API: Scheduled Notifications ───────────────────────────────────────────

class NotificationCreateRequest(BaseModel):
    device_id: str
    message: str
    target_users: list[str]
    is_recurring: bool
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    interval_minutes: Optional[int] = None

@app.post("/api/v1/notifications")
def create_notification(req: NotificationCreateRequest, db: Session = Depends(get_db)):
    """Create a new notification (one-off or recurring)."""
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if not req.is_recurring:
        # One-off: Just queue a command immediately
        cmd = Command(
            device_id=req.device_id,
            action="notify",
            username="system",
            payload=json.dumps({
                "message": req.message,
                "target_users": req.target_users
            })
        )
        db.add(cmd)
        db.commit()
        return {"message": "One-off notification queued."}
    
    # Recurring campaign
    if not req.start_time or not req.end_time or not req.interval_minutes:
        raise HTTPException(status_code=400, detail="Recurring notifications require start_time, end_time, and interval_minutes")
    
    try:
        st = datetime.fromisoformat(req.start_time.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        et = datetime.fromisoformat(req.end_time.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO-8601")

    camp = NotificationCampaign(
        device_id=req.device_id,
        message=req.message,
        target_users=json.dumps(req.target_users),
        start_time=st,
        end_time=et,
        interval_minutes=req.interval_minutes,
        is_active=True
    )
    db.add(camp)
    db.commit()
    db.refresh(camp)
    return {"message": "Recurring campaign created", "campaign_id": camp.id}

@app.get("/api/v1/notifications/{device_id}")
def get_notifications(device_id: str, db: Session = Depends(get_db)):
    """Get active recurring campaigns for a device."""
    campaigns = db.query(NotificationCampaign).filter(
        NotificationCampaign.device_id == device_id,
        NotificationCampaign.is_active == True
    ).order_by(NotificationCampaign.created_at.desc()).all()

    results = []
    for c in campaigns:
        results.append({
            "id": c.id,
            "message": c.message,
            "target_users": json.loads(c.target_users),
            "start_time": c.start_time.isoformat(timespec='milliseconds') + "Z",
            "end_time": c.end_time.isoformat(timespec='milliseconds') + "Z",
            "interval_minutes": c.interval_minutes,
            "last_sent": c.last_sent.isoformat(timespec='milliseconds') + "Z" if c.last_sent else None
        })
    return {"campaigns": results}

@app.delete("/api/v1/notifications/{campaign_id}")
def delete_notification(campaign_id: int, db: Session = Depends(get_db)):
    """Cancel a recurring campaign."""
    camp = db.query(NotificationCampaign).filter(NotificationCampaign.id == campaign_id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    camp.is_active = False
    db.commit()
    return {"message": "Campaign cancelled successfully"}
=======

# ── Auto-Revoke Background Scheduler ────────────────────────────────────────

def _auto_revoke_loop():
    """Runs every 15 seconds; finds expired grant commands and queues revokes."""
    import time as _time
    while True:
        _time.sleep(15)
        try:
            db = SessionLocal()
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            expired = (
                db.query(Command)
                .filter(
                    Command.action == "grant",
                    Command.status == "completed",
                    Command.auto_revoked == False,
                    Command.expires_at != None,
                    Command.expires_at <= now_utc,
                )
                .all()
            )
            for grant_cmd in expired:
                # Queue an auto-revoke for this user
                revoke_cmd = Command(
                    device_id=grant_cmd.device_id,
                    action="revoke",
                    username=grant_cmd.username,
                    payload="System Auto-Revoke"
                )
                db.add(revoke_cmd)
                grant_cmd.auto_revoked = True
            if expired:
                db.commit()
        except Exception:
            pass
        finally:
            db.close()


# Start the auto-revoke watcher in background when the module loads
_revoke_thread = threading.Thread(target=_auto_revoke_loop, daemon=True)
_revoke_thread.start()

>>>>>>> origin/development

# ── Serve Portal Static Files ───────────────────────────────────────────────

PORTAL_DIR = Path(__file__).resolve().parent.parent / "portal"


@app.get("/")
def serve_portal():
    """Serve the portal index.html."""
    index = PORTAL_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Portal not found. Place index.html in ../portal/"}


# Mount the portal directory for JS/CSS assets
if PORTAL_DIR.exists():
    app.mount("/portal", StaticFiles(directory=str(PORTAL_DIR)), name="portal")
