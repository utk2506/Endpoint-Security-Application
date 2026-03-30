"""
Admin Control System — Central Server
FastAPI application serving REST API + static portal files.
"""

import os
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json
import io
import csv
import threading
import time
import secrets
import string
import hashlib
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, status, Request, UploadFile, File, Form  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore
from fastapi.responses import FileResponse, StreamingResponse  # type: ignore
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm  # type: ignore
from pydantic import BaseModel  # type: ignore
from sqlalchemy.orm import Session  # type: ignore
from jose import JWTError, jwt  # type: ignore
from passlib.context import CryptContext # type: ignore
from models import SessionLocal, Device, Command, AdminSnapshot, EventLog, NotificationCampaign, User, InstalledSoftware, UninstallPassword, AgentVersion, ActivityEvent  # type: ignore

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


# ── Constants / Paths ───────────────────────────────────────────────────────

AGENT_SHARED_TOKEN = os.getenv("AGENT_SHARED_TOKEN")  # Optional shared bearer token for agents
UPDATES_DIR = Path(__file__).resolve().parent / "updates"
UPDATES_DIR.mkdir(parents=True, exist_ok=True)


# ── Security Configuration ──────────────────────────────────────────────────

SECRET_KEY = "super-secret-key-change-this-in-production"  # In a real app, use environment variables
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_agent_token(request: Request):
    """Validate shared bearer token for agent → server calls (if configured)."""
    if not AGENT_SHARED_TOKEN:
        return

    header = request.headers.get("Authorization") or request.headers.get("X-Agent-Token")
    token = None
    if header:
        if header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1]
        else:
            token = header

    if token != AGENT_SHARED_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent token",
        )


def _version_tuple(ver: Optional[str]) -> List[int]:
    if not ver:
        return []
    try:
        return [int(x) for x in ver.strip().lstrip("vV").split(".")]
    except Exception:
        return []


def is_version_newer(latest: Optional[str], current: Optional[str]) -> bool:
    """Return True if latest > current using simple semantic comparison."""
    l = _version_tuple(latest)
    c = _version_tuple(current)
    if not l or not c:
        return False  # can't compare versions; do not offer update for unknown current version
    return l > c

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token: Optional[str] = None

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]

    if not token:
        token = request.query_params.get("token")

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)):
    """Raises 403 if the logged-in user is not an admin."""
    if getattr(current_user, 'role', 'admin') != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to perform this action.",
        )
    return current_user


app = FastAPI(title="Admin Control System", version="1.0.0")

# ── Feature Routers ────────────────────────────────────────────────────────
from activity_service import activity_router  # type: ignore
app.include_router(activity_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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




# ── Pydantic schemas ────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    hostname: str
    ip_address: str
    system_info: Optional[dict] = None
    all_users: Optional[list[dict]] = None
    agent_version: Optional[str] = None
    install_path: Optional[str] = None


class SendCommandRequest(BaseModel):
    device_id: str
    action: str          # grant | revoke | check | shell | create_user | notify | get_bitlocker_key | uninstall_software
    username: Optional[str] = None
    payload: Optional[str] = None
    expires_at: Optional[str] = None   # ISO-8601 UTC string, e.g. "2026-03-14T18:30:00Z"


class CommandResultRequest(BaseModel):
    command_id: int
    status: str          # completed | failed
    result: Optional[str] = None
    admin_list: Optional[list[str]] = None   # populated for 'check' actions


class InstalledSoftwareItem(BaseModel):
    name: str
    version: Optional[str] = None
    publisher: Optional[str] = None
    install_date: Optional[str] = None
    uninstall_string: Optional[str] = None


class SoftwareInventoryPayload(BaseModel):
    device_id: str
    items: list[InstalledSoftwareItem]



class GenerateUninstallRequest(BaseModel):
    device_id: str


class VerifyUninstallRequest(BaseModel):
    device_id: str
    otp: str
    hostname: Optional[str] = None


# ── API: Authentication ────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str

@app.post("/api/auth/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/verify")
async def verify_token(current_user: User = Depends(get_current_user)):
    return {"status": "ok", "username": current_user.username}

@app.get("/api/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the current user's profile including their role."""
    return {
        "username": current_user.username,
        "role": getattr(current_user, 'role', 'admin'),
    }


# ── API: Device Management ──────────────────────────────────────────────────

@app.post("/register")
def register_device(
    req: RegisterRequest,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
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
        if req.agent_version:
            device.agent_version = req.agent_version
            device.last_version_check = datetime.now(timezone.utc)
        if req.install_path:
            device.install_path = req.install_path
        db.commit()
        db.refresh(device)
        return {"message": "Device updated", "device_id": device.id}

    device = Device(
        hostname=req.hostname,
        ip_address=req.ip_address,
        system_info=sys_info_str,
        all_users=all_users_str,
        agent_version=req.agent_version,
        install_path=req.install_path,
        last_version_check=datetime.now(timezone.utc) if req.agent_version else None,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return {"message": "Device registered", "device_id": device.id}


@app.get("/devices")
def list_devices(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
            "agent_version": d.agent_version,
            "last_version_check": d.last_version_check.isoformat(timespec='milliseconds') + "Z" if d.last_version_check else None,
            "install_path": d.install_path,
            "is_uninstalled": bool(d.is_uninstalled),
        }
        for d in devices
    ]


# ── API: Command Queue (Agent ↔ Server) ────────────────────────────────────

@app.post("/send_command")
def send_command(
    req: SendCommandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Portal queues a command for an agent to pick up."""
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    expires_at = None
    if req.expires_at:
        try:
            expires_at = datetime.fromisoformat(req.expires_at.replace("Z", "+00:00"))
        except Exception:
            pass

    cmd = Command(
        device_id=req.device_id,
        action=req.action,
        username=req.username,
        payload=req.payload,
        status="pending",
        expires_at=expires_at,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return {"message": "Command queued", "command_id": cmd.id}


@app.get("/get_command/{device_id}")
def get_command(
    device_id: str,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Agent polls for the next pending command."""
    # Update last_seen
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.last_seen = datetime.now(timezone.utc)

    # Auto-revoke any expired grants
    now = datetime.now(timezone.utc)
    expired = db.query(Command).filter(
        Command.device_id == device_id,
        Command.action == "grant",
        Command.status == "completed",
        Command.auto_revoked == False,
        Command.expires_at != None,
        Command.expires_at <= now,
    ).all()
    for exp in expired:
        revoke = Command(
            device_id=device_id,
            action="revoke",
            username=exp.username,
            status="pending",
        )
        db.add(revoke)
        exp.auto_revoked = True
    if expired:
        db.commit()

    cmd = db.query(Command).filter(
        Command.device_id == device_id,
        Command.status == "pending",
    ).order_by(Command.created_at.asc()).first()

    db.commit()

    if not cmd:
        return {"command": None}

    cmd.status = "executing"
    cmd.executed_at = datetime.now(timezone.utc)
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
def command_result(
    req: CommandResultRequest,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Agent reports the result of a command."""
    cmd = db.query(Command).filter(Command.id == req.command_id).first()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    cmd.status = req.status
    cmd.result = req.result

    if req.admin_list is not None:
        snapshot = AdminSnapshot(
            device_id=cmd.device_id,
            admin_users=json.dumps(req.admin_list),
        )
        db.add(snapshot)

    db.commit()
    return {"message": "Result recorded"}


@app.get("/commands/history")
def get_command_history(
    limit: int = 20,
    page: int = 1,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    device_id: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated command history for all or specific devices."""
    query = db.query(Command)
    if device_id:
        query = query.filter(Command.device_id == device_id)
    if action:
        query = query.filter(Command.action == action)
    if search:
        query = query.filter(
            (Command.username.ilike(f"%{search}%")) |
            (Command.payload.ilike(f"%{search}%")) |
            (Command.result.ilike(f"%{search}%"))
        )

    total = query.count()
    
    order_col = getattr(Command, sort_by, Command.created_at)
    if sort_dir == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())
        
    offset = (page - 1) * limit
    cmds = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "commands": [
            {
                "id": c.id,
                "device_id": c.device_id,
                "action": c.action,
                "username": c.username,
                "payload": c.payload,
                "status": c.status,
                "result": c.result,
                "created_at": c.created_at.isoformat(timespec="milliseconds") + "Z" if c.created_at else None,
                "executed_at": c.executed_at.isoformat(timespec="milliseconds") + "Z" if c.executed_at else None,
            }
            for c in cmds
        ]
    }


@app.get("/commands/{device_id}")
def get_commands(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return command history for a device."""
    cmds = (
        db.query(Command)
        .filter(Command.device_id == device_id)
        .order_by(Command.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": c.id,
            "action": c.action,
            "username": c.username,
            "payload": c.payload,
            "status": c.status,
            "result": c.result,
            "created_at": c.created_at.isoformat(timespec="milliseconds") + "Z" if c.created_at else None,
            "executed_at": c.executed_at.isoformat(timespec="milliseconds") + "Z" if c.executed_at else None,
            "expires_at": c.expires_at.isoformat(timespec="milliseconds") + "Z" if c.expires_at else None,
            "auto_revoked": c.auto_revoked,
        }
        for c in cmds
    ]


@app.get("/commands")
def get_all_commands(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent command history across all devices."""
    cmds = (
        db.query(Command)
        .order_by(Command.created_at.desc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": c.id,
            "device_id": c.device_id,
            "action": c.action,
            "username": c.username,
            "payload": c.payload,
            "status": c.status,
            "result": c.result,
            "created_at": c.created_at.isoformat(timespec="milliseconds") + "Z" if c.created_at else None,
            "executed_at": c.executed_at.isoformat(timespec="milliseconds") + "Z" if c.executed_at else None,
            "expires_at": c.expires_at.isoformat(timespec="milliseconds") + "Z" if c.expires_at else None,
            "auto_revoked": c.auto_revoked,
        }
        for c in cmds
    ]


# ── API: Event Logs ─────────────────────────────────────────────────────────

class EventLogPayload(BaseModel):
    device_id: str
    logs: list[dict]

@app.post("/api/v1/device/logs")
def ingest_event_logs(
    payload: EventLogPayload,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Receive event logs batch from agent."""
    device = db.query(Device).filter(Device.id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    now = datetime.now(timezone.utc)
    rows = []
    for entry in payload.logs:
        # Accept both old and new field naming conventions from agents
        ts_raw = entry.get("timestamp") or entry.get("occurred_at")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")) if ts_raw else now
        except Exception:
            ts = now

        rows.append(EventLog(
            device_id=payload.device_id,
            hostname=entry.get("hostname") or device.hostname,
            username=entry.get("username"),
            event_id=entry.get("event_id") or 0,
            event_name=entry.get("event_name") or entry.get("source", "unknown"),
            log_source=entry.get("log_source") or entry.get("log_channel", "System"),
            message=(entry.get("message") or "")[:4096],
            timestamp=ts,
            created_at=now,
        ))
    if rows:
        db.bulk_save_objects(rows)
    db.commit()
    return {"status": "ok", "count": len(rows)}


@app.get("/api/v1/device/{device_id}/logs")
def get_device_logs(
    device_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return event logs for a device."""
    logs = (
        db.query(EventLog)
        .filter(EventLog.device_id == device_id)
        .order_by(EventLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": l.id,
            "event_id": l.event_id,
            "event_name": l.event_name,
            "log_source": l.log_source,
            "hostname": l.hostname,
            "username": l.username,
            "message": l.message,
            "timestamp": l.timestamp.isoformat(timespec="milliseconds") + "Z" if l.timestamp else None,
        }
        for l in logs
    ]


# ── API: Notifications ──────────────────────────────────────────────────────

# ── API: Notifications ──────────────────────────────────────────────────────

class NotificationPayload(BaseModel):
    device_ids: list[str]               # support multiple targets
    message: str
    title: Optional[str] = "SentraGuard"
    target_users: Optional[list[str]] = ["All"]
    is_recurring: Optional[bool] = False
    start_time: Optional[str] = None    # ISO string; None = send immediately
    end_time: Optional[str] = None
    interval_minutes: Optional[int] = None


@app.post("/api/v1/notifications")
def send_notification(
    payload: NotificationPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a notification or create a recurring campaign for one or more devices."""
    now = datetime.now(timezone.utc)
    ids = []

    for device_id in payload.device_ids:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            continue  # skip unknown devices

        if payload.is_recurring:
            # Recurring campaign — store in notification_campaigns table
            st = datetime.fromisoformat(payload.start_time.replace("Z", "+00:00")) if payload.start_time else now
            et = datetime.fromisoformat(payload.end_time.replace("Z", "+00:00")) if payload.end_time else None
            campaign = NotificationCampaign(
                device_id=device_id,
                title=payload.title or "SentraGuard",
                message=payload.message,
                target_users=json.dumps(payload.target_users or ["All"]),
                start_time=st,
                end_time=et,
                interval_minutes=payload.interval_minutes or 5,
                is_active=True,
            )
            db.add(campaign)
            db.flush()
            ids.append(campaign.id)
        else:
            # One-time — queue a notify Command so the agent picks it up on next poll
            cmd = Command(
                device_id=device_id,
                action="notify",
                payload=json.dumps({"message": payload.message, "title": payload.title or "SentraGuard"}),
                status="pending",
            )
            db.add(cmd)
            db.flush()
            ids.append(cmd.id)

    db.commit()
    return {"status": "queued", "count": len(ids), "ids": ids}


@app.get("/notifications/{device_id}")
def get_notifications_agent(
    device_id: str,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Agent polls for pending recurring notification campaigns."""
    now = datetime.now(timezone.utc)
    active = (
        db.query(NotificationCampaign)
        .filter(
            NotificationCampaign.device_id == device_id,
            NotificationCampaign.is_active == True,
            NotificationCampaign.end_time > now,
        )
        .all()
    )

    due = []
    for n in active:
        if n.start_time and n.start_time > now:
            continue  # Not started yet
        interval_td = timedelta(minutes=n.interval_minutes or 5)
        if n.last_sent is None or (now - n.last_sent) >= interval_td:
            due.append(n)
            n.last_sent = now

    db.commit()
    return [{"id": n.id, "message": n.message, "title": n.title or "SentraGuard"} for n in due]


@app.delete("/api/v1/notifications/{campaign_id}")
def cancel_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate a recurring campaign."""
    c = db.query(NotificationCampaign).filter(NotificationCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.is_active = False
    db.commit()
    return {"status": "cancelled", "id": campaign_id}


# ── API: Admin Snapshots ────────────────────────────────────────────────────

@app.get("/admin_snapshots/{device_id}")
def get_admin_snapshots(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snapshots = (
        db.query(AdminSnapshot)
        .filter(AdminSnapshot.device_id == device_id)
        .order_by(AdminSnapshot.captured_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "admin_users": json.loads(s.admin_users) if s.admin_users else [],
            "captured_at": s.captured_at.isoformat(timespec="milliseconds") + "Z" if s.captured_at else None,
        }
        for s in snapshots
    ]


# ── API: Protected Uninstall OTP ────────────────────────────────────────────

@app.post("/generate-uninstall-password")
def generate_uninstall_password(
    req: GenerateUninstallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Invalidate any existing active OTPs for this device
    db.query(UninstallPassword).filter(
        UninstallPassword.device_id == req.device_id,
        UninstallPassword.used == False
    ).update({UninstallPassword.used: True})

    otp = "".join(secrets.choice(string.digits) for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    rec = UninstallPassword(
        device_id=req.device_id,
        otp_hash=pwd_context.hash(otp),
        expires_at=expires_at,
        issued_by=current_user.username if current_user else None,
        used=False,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {
        "otp": otp,
        "expires_at": expires_at.isoformat(),
        "device_id": req.device_id,
    }


@app.post("/verify-uninstall")
def verify_uninstall(
    req: VerifyUninstallRequest,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    now = datetime.now(timezone.utc)
    otp_row = (
        db.query(UninstallPassword)
        .filter(
            UninstallPassword.device_id == req.device_id,
            UninstallPassword.used == False,
            UninstallPassword.expires_at >= now,
        )
        .order_by(UninstallPassword.created_at.desc())
        .first()
    )

    if not otp_row:
        raise HTTPException(status_code=403, detail="No active uninstall OTP for this device")

    if not pwd_context.verify(req.otp, otp_row.otp_hash):
        raise HTTPException(status_code=403, detail="Invalid uninstall OTP")

    otp_row.used = True
    otp_row.used_at = now

    # Mark the device as explicitly uninstalled
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if device:
        device.is_uninstalled = True

    db.commit()

    return {"status": "ok", "device_id": req.device_id}


def _download_url(file_name: str, request: Request) -> str:
    base = str(request.base_url).rstrip("/") if request else ""
    return f"{base}/downloads/{file_name}"


@app.get("/agent/version")
def get_agent_version(
    current_version: Optional[str] = None,
    device_id: Optional[str] = None,
    db: Session = Depends(get_db),
    request: Request = None,
    agent_auth: None = Depends(require_agent_token),
):
    """Agent checks if a newer binary is available."""
    latest = (
        db.query(AgentVersion)
        .filter(AgentVersion.is_active == True)
        .order_by(AgentVersion.created_at.desc())
        .first()
    )

    if device_id:
        device = db.query(Device).filter(Device.id == device_id).first()
        if device:
            if current_version:
                device.agent_version = current_version
            device.last_version_check = datetime.now(timezone.utc)
            db.commit()

    if not latest:
        return {"update_available": False, "version": current_version}

    file_name = Path(latest.download_path).name
    download_url = _download_url(file_name, request)
    update_available = is_version_newer(latest.version, current_version)

    return {
        "version": latest.version,
        "download_url": download_url,
        "checksum_sha256": latest.checksum_sha256,
        "release_notes": latest.release_notes,
        "file_size": latest.file_size,
        "update_available": update_available,
    }


@app.post("/api/v1/admin/agent-version")
async def upload_agent_version(
    version: str = Form(...),
    file: UploadFile = File(...),
    release_notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    request: Request = None,
):
    """Upload and register a new signed agent binary."""
    if not version:
        raise HTTPException(status_code=400, detail="version is required")
    if not file:
        raise HTTPException(status_code=400, detail="agent binary file is required")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty agent binary")

    file_name = f"agent-{version}.exe"
    dest_path = UPDATES_DIR / file_name
    dest_path.write_bytes(data)
    checksum = hashlib.sha256(data).hexdigest()
    size = dest_path.stat().st_size

    # Mark older versions inactive
    db.query(AgentVersion).update({AgentVersion.is_active: False})
    rec = AgentVersion(
        version=version,
        download_path=file_name,
        checksum_sha256=checksum,
        release_notes=release_notes,
        is_active=True,
        file_size=size,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {
        "status": "ok",
        "version": version,
        "checksum_sha256": checksum,
        "download_url": _download_url(file_name, request),
        "file_size": size,
    }


@app.get("/api/v1/admin/agent-versions")
def list_agent_versions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    request: Request = None,
):
    """List uploaded agent binaries and their metadata."""
    rows = (
        db.query(AgentVersion)
        .order_by(AgentVersion.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "version": r.version,
                "platform": r.platform,
                "download_url": _download_url(Path(r.download_path).name, request),
                "checksum_sha256": r.checksum_sha256,
                "release_notes": r.release_notes,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat(timespec='milliseconds') + "Z" if r.created_at else None,
                "file_size": r.file_size,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@app.post("/api/v1/device/software")
def ingest_software_inventory(
    payload: SoftwareInventoryPayload,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Receive the full installed software list from an agent."""
    device = db.query(Device).filter(Device.id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Replace existing inventory for the device to avoid drift/duplicates
    db.query(InstalledSoftware).filter(InstalledSoftware.device_id == payload.device_id).delete()

    now_utc = datetime.now(timezone.utc)
    rows = []
    for item in payload.items:
        if not item.name:
            continue
        rows.append(
            InstalledSoftware(
                device_id=payload.device_id,
                name=item.name[:512],
                version=item.version[:100] if item.version else None,
                publisher=item.publisher[:255] if item.publisher else None,
                install_date=item.install_date[:32] if item.install_date else None,
                uninstall_string=item.uninstall_string,
                last_seen=now_utc,
                created_at=now_utc,
            )
        )

    if rows:
        db.bulk_save_objects(rows)
    db.commit()
    return {"status": "ok", "count": len(rows)}


@app.get("/api/v1/device/{device_id}/software")
def get_device_software(
    device_id: str,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return installed software for a device."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    query = db.query(InstalledSoftware).filter(InstalledSoftware.device_id == device_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (InstalledSoftware.name.ilike(pattern)) |
            (InstalledSoftware.publisher.ilike(pattern))
        )

    software = query.order_by(InstalledSoftware.name.asc()).all()
    return {
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "version": s.version,
                "publisher": s.publisher,
                "install_date": s.install_date,
                "uninstall_string": s.uninstall_string,
                "last_seen": s.last_seen.isoformat(timespec='milliseconds') + "Z" if s.last_seen else None,
            }
            for s in software
        ]
    }


# ── API: Portal — Event Log Viewer ──────────────────────────────────────────

@app.get("/api/v1/event-logs")
def list_event_logs(
    limit: int = 20,
    page: int = 1,
    sort_by: str = "timestamp",
    sort_dir: str = "desc",
    device_id: Optional[str] = None,
    log_source: Optional[str] = None,
    event_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated event log viewer for portal."""
    query = db.query(EventLog)
    if device_id:
        query = query.filter(EventLog.device_id == device_id)
    if log_source:
        query = query.filter(EventLog.log_source == log_source)
    if event_id:
        query = query.filter(EventLog.event_id == event_id)
    if search:
        query = query.filter(
            (EventLog.message.ilike(f"%{search}%")) |
            (EventLog.event_name.ilike(f"%{search}%")) |
            (EventLog.username.ilike(f"%{search}%"))
        )

    total = query.count()

    # Map sort column names to actual model attributes
    sort_col_map = {
        "timestamp": EventLog.timestamp,
        "hostname": EventLog.hostname,
        "username": EventLog.username,
        "event_id": EventLog.event_id,
        "event_name": EventLog.event_name,
        "log_source": EventLog.log_source,
    }
    order_col = sort_col_map.get(sort_by, EventLog.timestamp)
    if sort_dir == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    offset = (page - 1) * limit
    logs = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "logs": [
            {
                "id": l.id,
                "device_id": l.device_id,
                "hostname": l.hostname or "",
                "username": l.username or "",
                "event_id": l.event_id or 0,
                "event_name": l.event_name or "",
                "log_source": l.log_source or "",
                "message": l.message or "",
                "timestamp": l.timestamp.isoformat(timespec="milliseconds") + "Z" if l.timestamp else None,
            }
            for l in logs
        ],
    }


@app.get("/api/v1/event-logs/summary")
def event_logs_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Summary stats for the event log viewer — matches dashboard KPI cards."""
    try:
        total = db.query(EventLog).count()

        # Login events (Windows Security event_name values)
        login_names = ["logon", "logon_explicit", "logon_network", "logon_batch", "logon_service"]
        logins = db.query(EventLog).filter(EventLog.event_name.in_(login_names)).count()

        # Log-off events
        logoff_names = ["logoff", "logon_type_logoff"]
        logoffs = db.query(EventLog).filter(EventLog.event_name.in_(logoff_names)).count()

        # Crash / error events
        crash_names = ["app_crash", "unexpected_shutdown", "error_reporting", "app_hang",
                       "driver_init_failure", "disk_controller_error", "disk_error"]
        crashes = db.query(EventLog).filter(EventLog.event_name.in_(crash_names)).count()

        # Privilege escalation events
        priv_names = ["priv_use", "priv_service_op", "user_added_to_priv_group",
                      "user_removed_from_priv_group", "account_changed"]
        privilege_events = db.query(EventLog).filter(EventLog.event_name.in_(priv_names)).count()

        return {
            "total_events": total,
            "logins": logins,
            "logoffs": logoffs,
            "crashes": crashes,
            "privilege_events": privilege_events,
        }
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).error("event_logs_summary error: %s", exc)
        return {"total_events": 0, "logins": 0, "logoffs": 0, "crashes": 0, "privilege_events": 0}


# ── API: Portal — Notifications viewer ──────────────────────────────────────

@app.get("/api/v1/notifications/{device_id}")
def get_device_notifications(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return active notification campaigns for a device (portal view)."""
    try:
        campaigns = (
            db.query(NotificationCampaign)
            .filter(
                NotificationCampaign.device_id == device_id,
                NotificationCampaign.is_active == True,
            )
            .order_by(NotificationCampaign.created_at.desc())
            .limit(50)
            .all()
        )
        return {
            "campaigns": [
                {
                    "id": n.id,
                    "message": n.message,
                    "title": getattr(n, "title", None) or "SentraGuard",
                    "target_users": json.loads(n.target_users) if getattr(n, "target_users", None) else ["All"],
                    "interval_minutes": getattr(n, "interval_minutes", None) or 0,
                    "start_time": n.start_time.isoformat(timespec="milliseconds") + "Z" if getattr(n, "start_time", None) else None,
                    "end_time": n.end_time.isoformat(timespec="milliseconds") + "Z" if getattr(n, "end_time", None) else None,
                    "is_active": n.is_active,
                    "created_at": n.created_at.isoformat(timespec="milliseconds") + "Z" if n.created_at else None,
                }
                for n in campaigns
            ]
        }
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).error("get_device_notifications error: %s", exc)
        return {"campaigns": []}


# ── API: Portal — Admin list ─────────────────────────────────────────────────

@app.get("/admin_list/{device_id}")
def get_admin_list(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        "admin_users": json.loads(snapshot.admin_users) if snapshot.admin_users else [],
        "captured_at": snapshot.captured_at.isoformat(timespec="milliseconds") + "Z" if snapshot.captured_at else None,
    }


# ── API: Export Audit PDF/CSV ────────────────────────────────────────────────

@app.get("/api/v1/audit/export/{fmt}")
def export_audit(
    fmt: str,
    token: str,
    device_id: Optional[str] = None,
    action: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        from jose import jwt, JWTError
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    query = db.query(Command).order_by(Command.created_at.desc())
    if device_id: query = query.filter(Command.device_id == device_id)
    if action: query = query.filter(Command.action == action)
    cmds = query.limit(10000).all()

    import io
    if fmt.lower() == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Device ID", "Action", "Username", "Status", "Result", "Date"])
        for c in cmds:
            writer.writerow([c.id, c.device_id, c.action, c.username, c.status, c.result, c.created_at])
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audit.csv"})
        
    elif fmt.lower() == "pdf":
        from reportlab.pdfgen import canvas
        output = io.BytesIO()
        c = canvas.Canvas(output)
        c.setFont("Helvetica", 9)
        c.drawString(50, 800, "SentraGuard Audit Log Export")
        y = 780
        for cmd in cmds[:200]:  # Cap at 200 for PDF to keep it simple
            c.drawString(50, y, f"{cmd.created_at.replace(microsecond=0) if cmd.created_at else ''} | {str(cmd.device_id)[:8]} | {cmd.action} | {cmd.status} | {str(cmd.result)[:40]}")
            y -= 12
            if y < 50:
                c.showPage()
                c.setFont("Helvetica", 9)
                y = 800
        c.save()
        from fastapi.responses import Response
        return Response(output.getvalue(), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=audit.pdf"})

    raise HTTPException(status_code=400, detail="Invalid format")


# ── Legacy v1 Compatibility Endpoints ─────────────────────────────────────────

@app.get('/api/v1/activity')
def legacy_get_activity(
    request: Request, db: Session = Depends(get_db),
    page: int = 1, limit: int = 20,
    device_id: str = None, username: str = None, search: str = None,
    date_from: str = None, date_to: str = None
):
    from activity_service import get_events
    res = get_events(
        request=request, db=db, current_user=None, 
        machine=device_id, username=username, event_type=None, 
        synced=None, search=search, date_from=date_from, 
        date_to=date_to, page=page, limit=limit, format=None
    )
    res['items'] = res.pop('events', [])
    return res


@app.get('/api/v1/activity/stats')
def legacy_get_stats(
    request: Request, db: Session = Depends(get_db),
    device_id: str = None, date_from: str = None, date_to: str = None
):
    from activity_service import get_kpi
    res = get_kpi(request=request, db=db, current_user=None, window_minutes=30)
    return {
        'total_idle_seconds': res['idle'] * 60,
        'device_count': res['total_registered'],
        'process_distribution': {
            'System Idle Process': res['idle'] * 60,
            'Active Apps': res['active'] * 60
        }
    }


@app.get('/api/v1/activity/users')
def legacy_get_users(request: Request, db: Session = Depends(get_db)):
    from models import ActivityEvent
    q = db.query(ActivityEvent.username).distinct().all()
    return {'users': [x[0] for x in q if x[0]]}


@app.get('/api/v1/activity/device-summary')
def legacy_device_summary(request: Request, db: Session = Depends(get_db)):
    from activity_service import get_summary
    sum_data = get_summary(request=request, db=db, current_user=None, date_from=None, date_to=None)
    return {
        'devices': [
            {'device_id': getattr(row, 'machine', None) or row[0], 'username': None, 'active_seconds': (getattr(row, 'active_count', None) or row[2] or 0) * 60, 'idle_seconds': 0}
            for row in sum_data['by_machine']
        ]
    }


@app.get('/api/v1/activity/hourly')
def legacy_hourly(request: Request, db: Session = Depends(get_db)):
    from activity_service import get_summary
    sum_data = get_summary(request=request, db=db, current_user=None, date_from=None, date_to=None)
    return {'hourly': sum_data.get('hourly', [])}


@app.get('/api/v1/activity/summary')
def legacy_summary(request: Request, db: Session = Depends(get_db)):
    from activity_service import get_summary
    sum_data = get_summary(request=request, db=db, current_user=None, date_from=None, date_to=None)
    return {
        'users': [{'username': getattr(row, 'username', None) or row[0], 'event_count': getattr(row, 'total', None) or row[1]} for row in sum_data['by_user']]
    }


# ── Static File Serving (Must be at the end) ────────────────────────────────

# Locate portal dir: works whether app.py runs from server/ OR AdminControlSystem/
_candidate_1 = Path(__file__).resolve().parent.parent / "portal"
_candidate_2 = Path.cwd().parent / "portal"
_candidate_3 = Path.cwd() / "portal"
PORTAL_DIR = next(
    (p for p in [_candidate_1, _candidate_2, _candidate_3] if p.is_dir()),
    _candidate_1,  # fallback even if missing
)
import logging as _logging
_logging.getLogger("uvicorn").info(f"[ACS] Portal static dir: {PORTAL_DIR}")

@app.get("/")
def serve_index():
    return FileResponse(PORTAL_DIR / "index.html")

app.mount("/portal", StaticFiles(directory=str(PORTAL_DIR)), name="portal")

