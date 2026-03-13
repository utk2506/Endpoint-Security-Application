"""
Admin Control System — Central Server
FastAPI application serving REST API + static portal files.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import SessionLocal, Device, Command, AdminSnapshot

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Admin Control System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    device_id: int
    action: str          # grant | revoke | check
    username: Optional[str] = None


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
            "registered_at": d.registered_at.isoformat() if d.registered_at else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
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

    if req.action not in ("grant", "revoke", "check"):
        raise HTTPException(status_code=400, detail="Action must be grant, revoke, or check")

    if req.action in ("grant", "revoke") and not req.username:
        raise HTTPException(status_code=400, detail="Username required for grant/revoke")

    cmd = Command(
        device_id=req.device_id,
        action=req.action,
        username=req.username,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return {"message": "Command queued", "command_id": cmd.id}


@app.get("/get_command/{device_id}")
def get_command(device_id: int, db: Session = Depends(get_db)):
    """Agent polls: return the oldest pending command for a device."""
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
def get_admin_list(device_id: int, db: Session = Depends(get_db)):
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
def command_history(limit: int = 50, db: Session = Depends(get_db)):
    """Return recent command history across all devices."""
    cmds = (
        db.query(Command)
        .order_by(Command.created_at.desc())
        .limit(limit)
        .all()
    )
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
    return results


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
