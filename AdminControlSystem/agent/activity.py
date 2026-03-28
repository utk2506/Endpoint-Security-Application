"""
activity.py — User activity sampling: foreground window, idle time, click/key counts.
"""

import ctypes
import os
import time
from ctypes import wintypes
from datetime import datetime, timezone

from config import ACTIVITY_INTERVAL, WINDLL
from logger import log
from network import api_call

# ── Win32 constants ───────────────────────────────────────────────────────────

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]


# ── Shared input counters (reset after each sample) ───────────────────────────

_activity_counts: dict = {"clicks": 0, "keys": 0}


# ── Input listeners ───────────────────────────────────────────────────────────

def _start_input_listeners() -> None:
    """Start pynput background threads for click and key counts."""
    try:
        from pynput import mouse, keyboard  # type: ignore

        def on_click(x, y, button, pressed):
            if pressed:
                _activity_counts["clicks"] += 1

        def on_press(key):
            _activity_counts["keys"] += 1

        mouse.Listener(on_click=on_click).start()
        keyboard.Listener(on_press=on_press).start()
        log('INFO', "Input listeners (pynput) started for activity tracking.")
    except Exception as e:
        log('WARN', f"Could not start activity pynput listeners: {e}")


# ── Window / idle helpers ─────────────────────────────────────────────────────

def _get_process_name(pid: int) -> str:
    if not WINDLL:
        return ""
    try:
        h_proc = WINDLL.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buf))
            if WINDLL.kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            WINDLL.kernel32.CloseHandle(h_proc)
    except Exception:
        return ""
    return ""


def _get_foreground_window_info():
    """Return (title, process_name) for the current foreground window."""
    if not WINDLL:
        return None, None
    try:
        hwnd = WINDLL.user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        buf = ctypes.create_unicode_buffer(512)
        WINDLL.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()
        pid = wintypes.DWORD()
        WINDLL.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = _get_process_name(pid.value)
        return title or None, proc_name or None
    except Exception as e:
        log('WARN', f"_get_foreground_window_info error: {e}")
        return None, None


def _get_idle_seconds() -> int:
    if not WINDLL:
        return 0
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if WINDLL.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = WINDLL.kernel32.GetTickCount() - lii.dwTime
            return int(millis / 1000)
    except Exception:
        pass
    return 0


# ── Sample collection ─────────────────────────────────────────────────────────

def collect_activity_sample() -> dict:
    """Collect a single user activity snapshot and reset counters."""
    title, proc_name = _get_foreground_window_info()
    idle = _get_idle_seconds()
    clicks = _activity_counts["clicks"]
    keys = _activity_counts["keys"]
    _activity_counts["clicks"] = 0
    _activity_counts["keys"] = 0

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat(timespec='milliseconds').replace("+00:00", "") + "Z"

    try:
        current_user = os.getlogin()
    except Exception:
        current_user = os.environ.get('USERNAME') or "Unknown"

    return {
        "timestamp": now_iso,
        "username": current_user,
        "window_title": title or "",
        "process_name": proc_name or "",
        "idle_seconds": idle,
        "click_count": clicks,
        "keypress_count": keys,
    }


# ── Background thread ─────────────────────────────────────────────────────────

def activity_sampler_thread(server: str, device_id: str) -> None:
    """Background thread: samples activity and POSTs to server on a timer."""
    log('INFO', f"🧭 Activity sampler started (interval: {ACTIVITY_INTERVAL}s)")
    _start_input_listeners()
    while True:
        try:
            sample = collect_activity_sample()
            api_call(server, 'POST', '/api/v1/activity', {"device_id": device_id, "activities": [sample]})
        except Exception as e:
            log('WARN', f"Activity sampler error: {e}")
        time.sleep(ACTIVITY_INTERVAL)
