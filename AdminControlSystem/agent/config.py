"""
config.py — All agent constants, global flags, and runtime globals.
Every other module imports from here to avoid circular dependencies.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

# ── WinPTY ──────────────────────────────────────────────────────────────────

HAS_PYWINPTY = False
try:
    from winpty import PtyProcess, Backend  # type: ignore
    HAS_PYWINPTY = True
except ImportError:
    try:
        from pywinpty import PtyProcess, Backend  # type: ignore
        HAS_PYWINPTY = True
    except ImportError:
        pass

# ── Windows subprocess creation flags ───────────────────────────────────────

CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS: int = getattr(subprocess, "DETACHED_PROCESS", 0)
CREATE_NEW_PROCESS_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CREATE_DEFAULT_ERROR_MODE: int = getattr(subprocess, "CREATE_DEFAULT_ERROR_MODE", 0)

# ── Windows ctypes handle ────────────────────────────────────────────────────

WINDLL = getattr(ctypes, "windll", None)

# ── Agent identity & paths ───────────────────────────────────────────────────

AGENT_VERSION = "1.0.3"
SERVICE_NAME = "SentraGuard"
DEFAULT_INSTALL_DIR = r"C:\Program Files\SentraGuard"
PROGRAM_DATA_DIR = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "SentraGuard")

STATE_FILE = "agent_state.json"
UPDATE_STAGING_DIR = "updates"
SWAP_LOCK_FILE = "agent_swap.lock"
NOTIFY_QUEUE_FILE = "notify_queue.json"

# ── Timing constants ─────────────────────────────────────────────────────────

POLL_INTERVAL = 5            # seconds — main command poll
LOG_COLLECT_INTERVAL = 60    # seconds — Windows event log collection
SOFTWARE_REFRESH_INTERVAL = 600  # seconds — installed software inventory refresh
ACTIVITY_INTERVAL = 15       # seconds — user activity sampling

UPDATE_MIN_INTERVAL = 900    # 15 minutes
UPDATE_MAX_INTERVAL = 2700   # 45 minutes
WATCHDOG_INTERVAL = 8        # seconds

# ── Tray & update flags ──────────────────────────────────────────────────────

TRAY_FLAG_FILE = os.path.join(PROGRAM_DATA_DIR, "tray_relaunch.flag")
TRAY_SUPERVISOR_LOG = os.path.join(PROGRAM_DATA_DIR, "tray_supervisor.log")
TRAY_SUPERVISOR_INTERVAL = 90  # seconds between service-side tray checks

# ── Caches ───────────────────────────────────────────────────────────────────

# Avoids repeatedly calling manage-bde (which takes ~5 s per drive)
_recovery_keys_cache: dict = {}
