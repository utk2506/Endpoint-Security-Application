"""
Admin Control System — Central Server
FastAPI application serving REST API + static portal files.
"""

import os
import json
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
from fastapi.responses import FileResponse  # type: ignore
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm  # type: ignore
from pydantic import BaseModel  # type: ignore
from sqlalchemy.orm import Session  # type: ignore
from jose import JWTError, jwt  # type: ignore
from passlib.context import CryptContext  # type: ignore

from models import SessionLocal, Device, Command, AdminSnapshot, EventLog, NotificationCampaign, User, InstalledSoftware, ActivityLog, UninstallPassword, AgentVersion  # type: ignore

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
        return latest != current
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


class ActivityEntry(BaseModel):
    timestamp: Optional[str] = None  # ISO-8601
    window_title: Optional[str] = None
    process_name: Optional[str] = None
    idle_seconds: Optional[int] = 0
    click_count: Optional[int] = 0
    keypress_count: Optional[int] = 0


class ActivityPayload(BaseModel):
    device_id: str
    activities: list[ActivityEntry]


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


@app.post("/api/v1/activity")
def ingest_activity(
    payload: ActivityPayload,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
    """Agent posts sampled user activity telemetry."""
    device = db.query(Device).filter(Device.id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    rows = []
    now_utc = datetime.now(timezone.utc)
    for entry in payload.activities:
        try:
            ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00")) if entry.timestamp else now_utc
        except Exception:
            ts = now_utc

        rows.append(
            ActivityLog(
                device_id=payload.device_id,
                timestamp=ts,
                window_title=(entry.window_title or "")[:1024],
                process_name=(entry.process_name or "")[:260],
                idle_seconds=entry.idle_seconds or 0,
                click_count=entry.click_count or 0,
                keypress_count=entry.keypress_count or 0,
            )
        )

    if rows:
        db.bulk_save_objects(rows)
        db.commit()
    return {"status": "ok", "inserted": len(rows)}


@app.get("/api/v1/activity")
def get_activity(
    page: int = 1,
    limit: int = 50,
    device_id: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated user activity stream for the portal."""
    page = max(page, 1)
    limit = max(1, min(limit, 200))

    query = db.query(ActivityLog)
    if device_id:
        query = query.filter(ActivityLog.device_id == device_id)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (ActivityLog.window_title.ilike(pattern)) |
            (ActivityLog.process_name.ilike(pattern))
        )

    if date_from:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.filter(ActivityLog.timestamp >= df)
        except Exception:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.filter(ActivityLog.timestamp <= dt)
        except Exception:
            pass

    total = query.count()
    items = (
        query.order_by(ActivityLog.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "items": [
            {
                "id": a.id,
                "device_id": a.device_id,
                "timestamp": a.timestamp.isoformat(timespec='milliseconds') + "Z" if a.timestamp else None,
                "window_title": a.window_title,
                "process_name": a.process_name,
                "idle_seconds": a.idle_seconds,
                "click_count": a.click_count,
                "keypress_count": a.keypress_count,
            }
            for a in items
        ],
    }


# ── API: Command Queue ─────────────────────────────────────────────────────

@app.post("/send_command")
def send_command(req: SendCommandRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Queue a command for a device."""
    device = db.query(Device).filter(Device.id == req.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if req.action not in ("grant", "revoke", "check", "shell", "create_user", "notify", "get_bitlocker_key", "uninstall_software"):
        raise HTTPException(status_code=400, detail="Action must be grant, revoke, check, shell, create_user, notify, get_bitlocker_key, or uninstall_software")

    if req.action in ("grant", "revoke", "create_user") and not req.username:
        raise HTTPException(status_code=400, detail="Username required for grant/revoke/create_user")

    if req.action in ("shell", "create_user", "uninstall_software") and not req.payload:
        raise HTTPException(status_code=400, detail="Payload (script, password, or uninstall data) required for this command type")

    if req.action == "get_bitlocker_key" and not req.payload:
        raise HTTPException(status_code=400, detail="Drive letter required for get_bitlocker_key (e.g. C:)")

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
def get_command(
    device_id: str,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
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
def command_result(
    req: CommandResultRequest,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
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
def get_admin_list(device_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
def ingest_device_logs(
    payload: DeviceLogsPayload,
    db: Session = Depends(get_db),
    agent_auth: None = Depends(require_agent_token),
):
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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

# ── API: Scheduled Notifications ───────────────────────────────────────────

class NotificationCreateRequest(BaseModel):
    device_ids: list[str]
    message: str
    target_users: list[str]
    is_recurring: bool
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    interval_minutes: Optional[int] = None

@app.post("/api/v1/notifications")
def create_notification(req: NotificationCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Create a new notification (one-off or recurring) for multiple devices."""
    devices = db.query(Device).filter(Device.id.in_(req.device_ids)).all()
    if not devices:
        raise HTTPException(status_code=404, detail="No matching devices found")

    if not req.is_recurring:
        # One-off: Just queue a command immediately for each
        for d in devices:
            cmd = Command(
                device_id=d.id,
                action="notify",
                username="system",
                payload=json.dumps({
                    "message": req.message,
                    "target_users": req.target_users
                })
            )
            db.add(cmd)
        db.commit()
        return {"message": f"One-off notification queued for {len(devices)} devices."}
    
    # Recurring campaign
    if not req.start_time or not req.end_time or not req.interval_minutes:
        raise HTTPException(status_code=400, detail="Recurring notifications require start_time, end_time, and interval_minutes")
    
    try:
        st = datetime.fromisoformat(req.start_time.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        et = datetime.fromisoformat(req.end_time.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO-8601")

    created = 0
    for d in devices:
        camp = NotificationCampaign(
            device_id=d.id,
            message=req.message,
            target_users=json.dumps(req.target_users),
            start_time=st,
            end_time=et,
            interval_minutes=req.interval_minutes,
            is_active=True
        )
        db.add(camp)
        created += 1

    db.commit()
    return {"message": f"Recurring campaign created for {created} devices"}

@app.get("/api/v1/notifications/{device_id}")
def get_notifications(device_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
def delete_notification(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Cancel a recurring campaign."""
    camp = db.query(NotificationCampaign).filter(NotificationCampaign.id == campaign_id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    camp.is_active = False
    db.commit()
    return {"message": "Campaign cancelled successfully"}

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


# Start the background threads when the module loads
_revoke_thread = threading.Thread(target=_auto_revoke_loop, daemon=True)
_revoke_thread.start()

def _notification_scheduler_loop():
    """Runs every 30 seconds; fires pending notifications."""
    import time as _time
    from datetime import timedelta
    while True:
        _time.sleep(30)
        try:
            db = SessionLocal()
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            active_camps = db.query(NotificationCampaign).filter(
                NotificationCampaign.is_active == True,
                NotificationCampaign.start_time <= now_utc,
                NotificationCampaign.end_time >= now_utc
            ).all()

            for camp in active_camps:
                should_fire = False
                if not camp.last_sent:
                    should_fire = True
                else:
                    elapsed_mins = (now_utc - camp.last_sent).total_seconds() / 60.0
                    if elapsed_mins >= camp.interval_minutes:
                        should_fire = True

                if should_fire:
                    cmd = Command(
                        device_id=camp.device_id,
                        action="notify",
                        username="system",
                        payload=json.dumps({
                            "message": camp.message,
                            "target_users": json.loads(camp.target_users)
                        })
                    )
                    db.add(cmd)
                    camp.last_sent = now_utc

            # Handle expiry cleanup
            expired_camps = db.query(NotificationCampaign).filter(
                NotificationCampaign.is_active == True,
                NotificationCampaign.end_time < now_utc
            ).all()
            for EC in expired_camps:
                EC.is_active = False

            db.commit()
        except Exception:
            pass
        finally:
            db.close()

_notify_thread = threading.Thread(target=_notification_scheduler_loop, daemon=True)
_notify_thread.start()


# ── Audit Log Export ─────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse  # type: ignore
import csv, io

@app.get("/api/v1/audit/export/csv")
def export_audit_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the full command history as a CSV file."""
    cmds = db.query(Command).order_by(Command.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Device ID", "Action", "Username", "Payload", "Status", "Result", "Created At", "Executed At", "Expires At", "Auto Revoked"])
    for c in cmds:
        writer.writerow([
            c.id, c.device_id, c.action,
            c.username or "",
            "***" if c.action == "create_user" else (c.payload or ""),
            c.status, (c.result or "")[:200],
            c.created_at.isoformat() if c.created_at else "",
            c.executed_at.isoformat() if c.executed_at else "",
            c.expires_at.isoformat() if c.expires_at else "",
            str(c.auto_revoked or False),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@app.get("/api/v1/audit/export/pdf")
def export_audit_pdf(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the full command history as a PDF file."""
    try:
        from reportlab.lib.pagesizes import A4, landscape  # type: ignore
        from reportlab.lib import colors  # type: ignore
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer  # type: ignore
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed. Run: pip install reportlab")

    cmds = db.query(Command).order_by(Command.created_at.desc()).limit(500).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=20)
    styles = getSampleStyleSheet()
    elems = []

    elems.append(Paragraph("Admin Control System — Audit Log Export", styles["Title"]))
    elems.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
    elems.append(Spacer(1, 12))

    headers = ["ID", "Device ID", "Action", "User", "Status", "Result", "Created At"]
    data = [headers]
    for c in cmds:
        data.append([
            str(c.id),
            str(c.device_id)[:8] + "...",
            c.action,
            c.username or "—",
            c.status,
            (c.result or "")[:60],
            c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "—",
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2535")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elems.append(table)
    doc.build(elems)

    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=audit_log.pdf"},
    )


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
if UPDATES_DIR.exists():
    app.mount("/downloads", StaticFiles(directory=str(UPDATES_DIR)), name="downloads")

if PORTAL_DIR.exists():
    app.mount("/portal", StaticFiles(directory=str(PORTAL_DIR)), name="portal")
