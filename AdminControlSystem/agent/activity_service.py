"""
activity_service.py — SentraGuardActivityService
=================================================
Standalone Windows Service entry point for enterprise user-activity
monitoring.  Runs independently of the main SentraGuard agent.

Service Properties
------------------
  Name        : SentraGuardActivityService
  Display     : SentraGuard Activity Monitoring Service
  Description : Tracks user application usage, idle time, and input
                activity for enterprise productivity analytics.
  Startup     : Automatic
  Recovery    : Restart on failure
  Account     : LocalSystem

Run directly (dev mode):
    python activity_service.py --server https://SERVER:8000 [--no-verify-ssl]
"""

import argparse
import ctypes
import json
import os
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urllib_request, error as url_error

# ── Paths ─────────────────────────────────────────────────────────────────────

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SentraGuard"
LOG_DIR      = PROGRAM_DATA / "logs"
STATE_FILE   = PROGRAM_DATA / "agent_state.json"   # shared with main agent
ACTIVITY_DB  = PROGRAM_DATA / "activity.db"

PROGRAM_DATA.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

def _log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / "activity_service.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── Win32 setup ───────────────────────────────────────────────────────────────

WINDLL = getattr(ctypes, "windll", None)

if sys.platform == "win32" and WINDLL:
    try:
        hwnd = WINDLL.kernel32.GetConsoleWindow()
        if hwnd:
            WINDLL.user32.ShowWindow(hwnd, 0)   # SW_HIDE
        WINDLL.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

# ── State reader (shared with main agent) ────────────────────────────────────

def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

# ── Win32 constants/structures ────────────────────────────────────────────────

import ctypes.wintypes as wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

# ── Input counters (thread-safe via GIL on CPython ints) ─────────────────────

_click_count    = 0
_keypress_count = 0
_counters_lock  = threading.Lock()


def _start_input_listeners() -> None:
    """Attach pynput listeners to count mouse clicks and key presses."""
    try:
        from pynput import mouse, keyboard  # type: ignore

        def _on_click(x, y, button, pressed):
            global _click_count
            if pressed:
                with _counters_lock:
                    _click_count += 1

        def _on_press(key):
            global _keypress_count
            with _counters_lock:
                _keypress_count += 1

        mouse.Listener(on_click=_on_click, suppress=False).start()
        keyboard.Listener(on_press=_on_press, suppress=False).start()
        _log("INFO", "Input listeners started (pynput).")
    except Exception as e:
        _log("WARN", f"Could not start pynput listeners: {e}")


def _drain_counters() -> tuple:
    """Atomically read and reset click/key counters."""
    global _click_count, _keypress_count
    with _counters_lock:
        c, k = _click_count, _keypress_count
        _click_count = 0
        _keypress_count = 0
    return c, k

# ── Window / idle helpers ─────────────────────────────────────────────────────

def _get_process_name(pid: int) -> str:
    if not WINDLL:
        return ""
    try:
        h = WINDLL.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf  = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buf))
            if WINDLL.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            WINDLL.kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _get_foreground_info() -> tuple:
    """Return (window_title, process_name) for the active foreground window."""
    if not WINDLL:
        return "", ""
    try:
        hwnd = WINDLL.user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        buf = ctypes.create_unicode_buffer(512)
        WINDLL.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()
        pid   = wintypes.DWORD()
        WINDLL.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _get_process_name(pid.value)
        return title, proc
    except Exception:
        return "", ""


def _get_idle_seconds() -> int:
    if not WINDLL:
        return 0
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if WINDLL.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = WINDLL.kernel32.GetTickCount() - lii.dwTime
            return max(0, int(millis / 1000))
    except Exception:
        pass
    return 0

# ── Browser URL extraction from window title ──────────────────────────────────

import re

_BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

# Patterns to strip browser name suffixes:
#   "My Page - Google Chrome"  →  "My Page"
#   "Something | Mozilla Firefox"  →  "Something"
_BROWSER_SUFFIX_RE = re.compile(
    r"[\s\-–|]+(?:Google Chrome|Mozilla Firefox|Microsoft Edge|Brave|Opera)[^|]*$",
    re.IGNORECASE,
)

# Loose URL pattern inside a title
_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?([a-z0-9\-]+\.[a-z]{2,})(?:[/\w\-\.?=&%#]*)?",
    re.IGNORECASE,
)


def _extract_browser_url(window_title: str, process_name: str) -> str:
    """
    Attempt to extract a domain / URL from a browser window title.
    Returns empty string for non-browser processes or when not parseable.
    """
    if not process_name or process_name.lower() not in _BROWSER_PROCESSES:
        return ""
    if not window_title:
        return ""

    # Strip browser chrome suffix
    clean = _BROWSER_SUFFIX_RE.sub("", window_title).strip()

    # Try to find a URL-like segment directly in the title
    m = _URL_RE.search(clean)
    if m:
        return m.group(0).lower()

    return ""

# ── Activity sample builder ───────────────────────────────────────────────────

def _collect_sample(device_id: str, username: str) -> dict:
    """Return one activity snapshot dict."""
    title, proc = _get_foreground_info()
    idle        = _get_idle_seconds()
    clicks, keys = _drain_counters()
    url         = _extract_browser_url(title, proc)

    now_iso = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "") + "Z"
    )

    return {
        "timestamp":      now_iso,
        "device_id":      device_id,
        "username":       username,
        "process_name":   proc or "",
        "window_title":   title or "",
        "url":            url,
        "idle_seconds":   idle,
        "mouse_clicks":   clicks,
        "keypress_count": keys,
    }

# ── Idle state classifier ─────────────────────────────────────────────────────

def _idle_state(idle_seconds: int) -> str:
    """Map idle seconds to a human-readable state per the spec."""
    if idle_seconds < 60:
        return "active"
    if idle_seconds < 300:
        return "idle"
    return "away"

# ── Main collection loop ──────────────────────────────────────────────────────

SAMPLE_INTERVAL = 15   # seconds — how often we snapshot activity

def _collection_loop(server: str, device_id: str, username: str,
                     auth_token: str, ssl_ctx: ssl.SSLContext) -> None:
    """
    Samples activity every SAMPLE_INTERVAL seconds.
    Writes to SQLite; sync_engine uploads the buffer to the server.
    """
    import sqlite_manager as sqlite_mgr

    _log("INFO", f"Collection loop started — sampling every {SAMPLE_INTERVAL}s")
    _start_input_listeners()

    while True:
        try:
            sample = _collect_sample(device_id, username)
            state  = _idle_state(sample["idle_seconds"])
            sqlite_mgr.save_activity(sample)
            pending = sqlite_mgr.pending_count()
            _log(
                "DEBUG",
                f"Sampled: proc={sample['process_name']!r:25s} "
                f"idle={sample['idle_seconds']:4d}s state={state} "
                f"clicks={sample['mouse_clicks']} keys={sample['keypress_count']} "
                f"pending={pending}"
            )
        except Exception as e:
            _log("WARN", f"Collection error: {e}")
        time.sleep(SAMPLE_INTERVAL)

# ── Registration helper ───────────────────────────────────────────────────────

def _get_username() -> str:
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "Unknown"


def _wait_for_device_id(server: str, ssl_ctx: ssl.SSLContext,
                         auth_token: str, timeout: int = 120) -> str | None:
    """
    Read device_id from shared agent_state.json.
    If not yet present, wait up to *timeout* seconds for the main agent
    to register and write it.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = _load_state()
        did   = state.get("device_id")
        if did:
            return did
        _log("INFO", "Waiting for main agent to register device_id…")
        time.sleep(5)
    return None

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SentraGuard Activity Monitoring Service"
    )
    parser.add_argument("--server",        default="https://localhost:8000")
    parser.add_argument("--no-verify-ssl", action="store_true")
    parser.add_argument("--token",         default=os.environ.get("AGENT_TOKEN"))
    parser.add_argument("--device-id",     default=None,
                        help="Override device-id (usually read from agent_state.json)")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    _log("INFO", "=" * 60)
    _log("INFO", "SentraGuard Activity Monitoring Service starting…")
    _log("INFO", f"  Server      : {server}")
    _log("INFO", f"  DB path     : {ACTIVITY_DB}")
    _log("INFO", f"  Log dir     : {LOG_DIR}")
    _log("INFO", "=" * 60)

    # Build SSL context
    ssl_ctx = ssl.create_default_context()
    if args.no_verify_ssl:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = ssl.CERT_NONE
        _log("WARN", "SSL certificate verification is DISABLED.")

    auth_token = args.token or ""

    # Get device_id
    device_id = args.device_id or _wait_for_device_id(server, ssl_ctx, auth_token)
    if not device_id:
        _log("ERROR", "Could not obtain device_id — aborting. "
                      "Ensure the main SentraGuard service is running first.")
        sys.exit(1)

    username = _get_username()
    _log("INFO", f"Monitoring user: {username!r}, device: {device_id!r}")

    # Start sync engine in background thread
    import sync_engine
    sync_thread = threading.Thread(
        target=sync_engine.start_sync_engine,
        args=(server, device_id, auth_token, ssl_ctx),
        daemon=True,
        name="SG-SyncEngine",
    )
    sync_thread.start()

    # Run collection loop on main thread (blocks until process exits)
    try:
        _collection_loop(server, device_id, username, auth_token, ssl_ctx)
    except KeyboardInterrupt:
        _log("INFO", "Service stopping (KeyboardInterrupt).")


if __name__ == "__main__":
    main()
