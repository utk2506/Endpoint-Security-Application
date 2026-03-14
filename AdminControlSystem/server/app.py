"""
Admin Control System — Central Server
FastAPI application serving REST API + static portal files.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore
from fastapi.responses import FileResponse  # type: ignore
from pydantic import BaseModel  # type: ignore
from sqlalchemy.orm import Session  # type: ignore

from models import SessionLocal, Device, Command, AdminSnapshot  # type: ignore

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


class SendCommandRequest(BaseModel):
    device_id: str
    action: str          # grant | revoke | check | shell
    username: Optional[str] = None
    payload: Optional[str] = None


class CommandResultRequest(BaseModel):
    command_id: int
    status: str          # completed | failed
    result: Optional[str] = None
    admin_list: Optional[list[str]] = None   # populated for 'check' actions


# ── API: Device Management ──────────────────────────────────────────────────

@app.post("/register")
def register_device(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new device or update last_seen for an existing one."""
    device = db.query(Device).filter(Device.hostname == req.hostname).first()
    if device:
        device.ip_address = req.ip_address
        device.last_seen = datetime.now(timezone.utc)
        db.commit()
        db.refresh(device)
        return {"message": "Device updated", "device_id": device.id}

    device = Device(hostname=req.hostname, ip_address=req.ip_address)
    db.add(device)
    db.commit()
    db.refresh(device)
    return {"message": "Device registered", "device_id": device.id}


@app.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """Return all registered devices."""
    devices = db.query(Device).order_by(Device.hostname).all()
    return [
        {
            "id": d.id,
            "hostname": d.hostname,
            "ip_address": d.ip_address,
            "registered_at": d.registered_at.isoformat(timespec='milliseconds') + "Z" if d.registered_at else None,
            "last_seen": d.last_seen.isoformat(timespec='milliseconds') + "Z" if d.last_seen else None,
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

    if req.action not in ("grant", "revoke", "check", "shell"):
        raise HTTPException(status_code=400, detail="Action must be grant, revoke, check, or shell")

    if req.action in ("grant", "revoke") and not req.username:
        raise HTTPException(status_code=400, detail="Username required for grant/revoke")

    if req.action == "shell" and not req.payload:
        raise HTTPException(status_code=400, detail="Payload required for shell commands")

    cmd = Command(
        device_id=req.device_id,
        action=req.action,
        username=req.username,
        payload=req.payload,
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
            "status": c.status,
            "result": c.result,
            "created_at": c.created_at.isoformat(timespec='milliseconds') + "Z" if c.created_at else None,
            "executed_at": c.executed_at.isoformat(timespec='milliseconds') + "Z" if c.executed_at else None,
        })
        
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "commands": results
    }


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
