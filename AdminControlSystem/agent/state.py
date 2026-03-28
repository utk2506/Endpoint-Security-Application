"""
state.py — Agent persistent state file helpers and notification queue.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import STATE_FILE, NOTIFY_QUEUE_FILE, CREATE_NO_WINDOW
from logger import log


# ── Path helpers ─────────────────────────────────────────────────────────────

def runtime_root() -> Path:
    """Return the directory that contains the running binary or script."""
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def state_file_path() -> Path:
    return runtime_root() / STATE_FILE


def notify_queue_path() -> Path:
    """Queue file lives in ProgramData so both service (SYSTEM) and users can access it."""
    base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "YourAgent"
    try:
        base.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["icacls", str(base), "/grant", "Users:(OI)(CI)M", "/T", "/Q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass
    return base / NOTIFY_QUEUE_FILE


# ── State read / write ────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(state_file_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(data: dict) -> None:
    try:
        state_file_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log("WARN", f"Could not persist agent state: {e}")


def update_state(**kwargs) -> None:
    state = load_state()
    state.update(kwargs)
    save_state(state)


# ── Notification queue ────────────────────────────────────────────────────────

def enqueue_notification(message: str) -> None:
    """Persist a notification so a user-session tray process can display it."""
    try:
        path = notify_queue_path()
        queue: list = []
        if path.exists():
            queue = json.loads(path.read_text(encoding="utf-8"))
        queue.append({
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
        log("INFO", "Notification queued for interactive session.")
    except Exception as e:
        log("WARN", f"Could not queue notification: {e}")


def dequeue_notification() -> "str | None":
    """Pop the oldest queued notification (if any)."""
    try:
        path = notify_queue_path()
        if not path.exists():
            return None
        queue = json.loads(path.read_text(encoding="utf-8"))
        if not queue:
            return None
        item = queue.pop(0)
        path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
        return item.get("message")
    except Exception as e:
        log("WARN", f"Could not read notification queue: {e}")
        return None


# ── Misc file helpers ─────────────────────────────────────────────────────────

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def compute_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
