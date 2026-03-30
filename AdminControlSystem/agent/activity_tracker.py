"""
activity_tracker.py — SentraGuard Endpoint User Activity Monitors

Tracks:
  LOGIN / LOGOUT   — via quser session differences
  LOCK / UNLOCK    — via LogonUI.exe presence
  IDLE / ACTIVE    — via GetLastInputInfo() idle threshold
  SCREEN_OFF/ON    — via WM_POWERBROADCAST PBT_POWERSETTINGCHANGE (MONITOR_POWER)
  STARTUP          — on service start
  SHUTDOWN         — on service stop (atexit)

All events are written to the local SQLite cache. A separate sync loop
(run by SentraGuardSyncService) reads the cache and uploads to the portal.
"""

import atexit
import ctypes
import ctypes.wintypes
import os
import platform
import subprocess
import threading
import time
from datetime import datetime, timezone

from activity_db import init_db, insert_event, get_unsynced, delete_synced
from logger import log
import network
# Reuse canonical telemetry functions from system_info (hostname, BIOS serial, IP)
from system_info import get_hostname, get_ip, collect_system_info

# ── Constants ────────────────────────────────────────────────────────────────

IDLE_THRESHOLD_SECONDS = 60    # 1 minute
POLL_INTERVAL_SECONDS  = 5     # 5 seconds
SYNC_INTERVAL_SECONDS  = 15    # 15-second background sync cadence

# Events that should trigger an immediate sync rather than waiting
_IMMEDIATE_SYNC_EVENTS = {"LOGIN", "LOGOUT", "LOCK", "UNLOCK", "IDLE", "ACTIVE", "STARTUP", "SHUTDOWN"}

# Set this event to wake the sync loop early (e.g. on a state change)
_sync_now = threading.Event()

# Windows GUID for monitor power state (PBT_POWERSETTINGCHANGE)
_MONITOR_POWER_GUID = "{02731015-4510-4526-99E6-E5A17EBD1AEA}"

# ── Device metadata (cached at startup) ──────────────────────────────────────

_device_meta: dict = {}
_device_meta_lock = threading.Lock()


def _get_device_meta() -> dict:
    """
    Collect machine/serial/IP/OS once and cache.
    Uses collect_system_info() from system_info.py for the BIOS serial
    (same source as the rest of the agent), with lightweight fallbacks.
    """
    global _device_meta
    with _device_meta_lock:
        if _device_meta:
            return _device_meta

    # Try the rich PowerShell-based collector first
    try:
        info = collect_system_info() or {}
    except Exception:
        info = {}

    machine    = (info.get("hostname") or get_hostname()).strip().lower()
    serial     = info.get("serial_number") or ""
    ip_address = get_ip()                            # always fresh UDP probe
    os_version = (
        f"{info.get('os_name', '')} {info.get('os_version', '')}".strip()
        or platform.version()
    )

    meta = {
        "machine":    machine,
        "serial":     serial,
        "ip_address": ip_address,
        "os_version": os_version,
    }
    with _device_meta_lock:
        _device_meta = meta
    log("INFO", f"Device meta cached — machine={machine}, serial={serial}, ip={ip_address}")
    return meta


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_active_username() -> str:
    """Return the username of the active interactive session via quser."""
    try:
        out = subprocess.check_output(
            ["quser"],
            encoding="utf-8", errors="replace",
            creationflags=0x08000000,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if not line.strip() or line.lower().startswith("username"):
                continue
            parts = line.replace(">", " ").split()
            if len(parts) >= 4 and parts[3].lower().startswith("active"):
                return parts[0]
    except Exception:
        pass
    return "SYSTEM"


def _get_last_input_idle_seconds() -> float:
    """Return seconds since last keyboard/mouse input using Win32 GetLastInputInfo."""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        liinfo = LASTINPUTINFO()
        liinfo.cbSize = ctypes.sizeof(liinfo)
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # Use 32-bit GetTickCount so both values are in the same 32-bit space
        kernel32.GetTickCount.restype = ctypes.c_ulong
        if user32.GetLastInputInfo(ctypes.byref(liinfo)):
            uptime_ms = kernel32.GetTickCount()
            # Handle 32-bit wraparound (uptime wraps every ~49 days)
            idle_ms = int((uptime_ms - liinfo.dwTime) & 0xFFFFFFFF)
            return idle_ms / 1000.0
    except Exception:
        pass
    return 0.0


def _is_screen_locked() -> bool:
    """Detect screen lock via LogonUI.exe process presence."""
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and proc.info["name"].lower() == "logonui.exe":
                return True
    except Exception:
        pass
    return False


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m {seconds % 60}s"
    hours = minutes // 60
    return f"{hours}h {minutes % 60}m"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log_event(event: str, username: str, duration: str = "0s"):
    meta = _get_device_meta()

    # Log to file so the user can see the service is working
    log("INFO", f"activity: Captured event [{event}] for user [{username}]")

    insert_event(
        timestamp  = _now_iso(),
        event      = event,
        username   = username,
        duration   = duration,
        machine    = meta["machine"],
        serial     = meta["serial"],
        ip_address = meta["ip_address"],
        os_version = meta["os_version"],
    )

    # Wake the sync loop immediately for state-change events so the portal
    # reflects the new status within seconds rather than waiting 15+ seconds.
    if event in _IMMEDIATE_SYNC_EVENTS:
        _sync_now.set()


# ── Input Counters (pynput) ──────────────────────────────────────────────────

_click_count: int = 0
_key_count: int   = 0
_input_lock       = threading.Lock()


def _on_click(*_):
    global _click_count
    with _input_lock:
        _click_count += 1


def _on_key(*_):
    global _key_count
    with _input_lock:
        _key_count += 1


def _drain_inputs() -> tuple[int, int]:
    """Atomically read and reset mouse + keyboard counters."""
    global _click_count, _key_count
    with _input_lock:
        c, k = _click_count, _key_count
        _click_count = _key_count = 0
    return c, k


def _start_input_listeners():
    """Start pynput mouse + keyboard listeners as daemon threads.
    Each listener runs in its own daemon thread so a failure in one
    does not crash the service or block the other."""
    import threading

    def _mouse_thread():
        try:
            from pynput import mouse as pm
            pm.Listener(on_click=_on_click).start()
            log("INFO", "activity_tracker: mouse listener started")
        except BaseException as e:
            log("WARN", f"activity_tracker: mouse listener failed: {e}")

    def _kb_thread():
        try:
            from pynput import keyboard as pk
            pk.Listener(on_press=_on_key).start()
            log("INFO", "activity_tracker: keyboard listener started")
        except BaseException as e:
            log("WARN", f"activity_tracker: keyboard listener failed: {e}")

    threading.Thread(target=_mouse_thread, daemon=True, name="MouseListenerInit").start()
    threading.Thread(target=_kb_thread,    daemon=True, name="KbListenerInit").start()
    log("INFO", "activity_tracker: input listener threads launched")


# ── Foreground App Tracker ─────────────────────────────────────────────────────

APP_SAMPLE_INTERVAL = 30   # seconds between APP_USAGE snapshots

_BROWSER_SUFFIXES = [
    " - Google Chrome", " - Mozilla Firefox", " - Microsoft Edge",
    " - Brave", " - Opera", " - Internet Explorer",
]


def _get_foreground_app() -> tuple[str, str, str]:
    """
    Return (process_name, window_title, url) for the current foreground window.
    URL is approximated by stripping the browser suffix from the window title.
    """
    try:
        user32   = ctypes.windll.user32
        hwnd     = user32.GetForegroundWindow()
        if not hwnd:
            return "", "", ""

        # Window title
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf    = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title  = buf.value.strip()

        # Process name via PID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = ""
        if pid.value:
            try:
                import psutil
                proc_name = psutil.Process(pid.value).name()
            except Exception:
                pass

        # URL approximation from browser title
        url = ""
        for suffix in _BROWSER_SUFFIXES:
            if title.endswith(suffix):
                url = title[: -len(suffix)].strip()
                break

        return proc_name, title, url
    except Exception:
        return "", "", ""


def _log_app_event(username: str, process_name: str, window_title: str,
                   url: str, idle_seconds: int, mouse_clicks: int, keypress_count: int):
    """Write an APP_USAGE event to the local cache."""
    meta = _get_device_meta()
    insert_event(
        timestamp      = _now_iso(),
        event          = "APP_USAGE",
        username       = username,
        duration       = "0s",
        machine        = meta["machine"],
        serial         = meta["serial"],
        ip_address     = meta["ip_address"],
        os_version     = meta["os_version"],
        process_name   = process_name,
        window_title   = window_title,
        url            = url,
        idle_seconds   = idle_seconds,
        mouse_clicks   = mouse_clicks,
        keypress_count = keypress_count,
    )


class _AppUsageThread(threading.Thread):
    """
    Daemon thread that samples the foreground window every APP_SAMPLE_INTERVAL
    seconds and logs APP_USAGE events to the local SQLite cache.
    """
    def __init__(self):
        super().__init__(daemon=True, name="AppUsageSampler")

    def run(self):
        log("INFO", "AppUsageSampler: started")
        while True:
            time.sleep(APP_SAMPLE_INTERVAL)
            try:
                if _is_screen_locked():
                    continue
                username = _get_active_username()
                if not username or username.upper() == "SYSTEM":
                    continue
                idle_secs = int(_get_last_input_idle_seconds())
                proc_name, win_title, url = _get_foreground_app()
                if not proc_name:
                    continue
                clicks, keys = _drain_inputs()
                _log_app_event(username, proc_name, win_title, url, idle_secs, clicks, keys)
            except Exception as e:
                log("WARN", f"AppUsageSampler error: {e}")


# ── Screen State Thread (WM_POWERBROADCAST) ───────────────────────────────────

class _ScreenMonitorThread(threading.Thread):
    """
    Registers a hidden Win32 window to receive WM_POWERBROADCAST messages.
    Fires SCREEN_ON / SCREEN_OFF events when the monitor power state changes.
    """

    WM_POWERBROADCAST          = 0x0218
    PBT_POWERSETTINGCHANGE     = 0x8013
    GUID_MONITOR_POWER_ON      = "{02731015-4510-4526-99E6-E5A17EBD1AEA}"

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self.name = "ScreenMonitorThread"

    def run(self):
        try:
            self._run_message_loop()
        except BaseException as e:
            log("WARN", f"ScreenMonitorThread error: {e}")

    def _run_message_loop(self):
        import ctypes
        import ctypes.wintypes

        WA = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        WNDPROCTYPE = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int
        )

        # Define WNDCLASSW manually — ctypes.wintypes does not include it
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style",         ctypes.c_uint),
                ("lpfnWndProc",   WNDPROCTYPE),
                ("cbClsExtra",    ctypes.c_int),
                ("cbWndExtra",    ctypes.c_int),
                ("hInstance",     ctypes.wintypes.HANDLE),
                ("hIcon",         ctypes.wintypes.HANDLE),
                ("hCursor",       ctypes.wintypes.HANDLE),
                ("hbrBackground", ctypes.wintypes.HANDLE),
                ("lpszMenuName",  ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == self.WM_POWERBROADCAST and wparam == self.PBT_POWERSETTINGCHANGE:
                try:
                    data = ctypes.cast(lparam, ctypes.POINTER(ctypes.c_byte * 24))
                    value = data.contents[20]
                    if value == 0:
                        self.callback("SCREEN_OFF")
                    elif value in (1, 2):
                        self.callback("SCREEN_ON")
                except Exception:
                    pass
            if msg == 0x0010:  # WM_DESTROY
                WA.PostQuitMessage(0)
            return WA.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROCTYPE(wndproc)
        classname = "SentraGuardActivityWnd"

        kernel32.GetModuleHandleW.restype = ctypes.wintypes.HINSTANCE if hasattr(ctypes.wintypes, 'HINSTANCE') else ctypes.c_void_p

        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc   = proc
        wndclass.hInstance     = kernel32.GetModuleHandleW(None)
        wndclass.lpszClassName = classname

        WA.RegisterClassW(ctypes.byref(wndclass))
        WA.CreateWindowExW.restype = ctypes.wintypes.HWND
        WA.CreateWindowExW.argtypes = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.wintypes.HWND, ctypes.wintypes.HMENU, ctypes.wintypes.HINSTANCE if hasattr(ctypes.wintypes, 'HINSTANCE') else ctypes.wintypes.HANDLE, ctypes.c_void_p
        ]
        
        hwnd = WA.CreateWindowExW(
            0, classname, "SentraGuardActivity", 0,
            0, 0, 0, 0, 0, 0, wndclass.hInstance, None
        )

        if not hwnd:
            log("WARN", "ScreenMonitorThread: CreateWindowExW failed — screen events disabled")
            return

        # Register for monitor power notifications
        DEVICE_NOTIFY_WINDOW_HANDLE = 0
        WA.RegisterPowerSettingNotification(
            hwnd,
            ctypes.create_string_buffer(
                b'\x15\x10\x73\x02\x10\x45\x26\x45'
                b'\x99\xe6\xe5\xa1\x7e\xbd\x1a\xea'
            ),
            DEVICE_NOTIFY_WINDOW_HANDLE
        )

        msg = ctypes.wintypes.MSG()
        while WA.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            WA.TranslateMessage(ctypes.byref(msg))
            WA.DispatchMessageW(ctypes.byref(msg))



# ── Main Activity Collection Loop ─────────────────────────────────────────────

_STARTUP_DEBOUNCE_SECONDS = 120  # don't emit STARTUP more than once per 2 min

# Persist last-startup time to disk so debounce survives process restarts
_STARTUP_STAMP_PATH = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "SentraGuard", "last_startup.txt"
)


def _startup_is_debounced() -> bool:
    """Return True if a STARTUP was logged within the debounce window."""
    try:
        with open(_STARTUP_STAMP_PATH, "r") as f:
            ts = float(f.read().strip())
        return (time.time() - ts) < _STARTUP_DEBOUNCE_SECONDS
    except Exception:
        return False


def _stamp_startup():
    """Write current time to the debounce stamp file."""
    try:
        os.makedirs(os.path.dirname(_STARTUP_STAMP_PATH), exist_ok=True)
        with open(_STARTUP_STAMP_PATH, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def activity_collection_loop():
    """
    Main state-machine loop polling user state every POLL_INTERVAL_SECONDS.
    Tracks LOGIN/LOGOUT, LOCK/UNLOCK, and IDLE/ACTIVE transitions.
    Screen state is handled in a separate WM_POWERBROADCAST thread.
    """
    global _last_startup_ts

    last_state           = "ACTIVE"
    last_user            = "SYSTEM"
    last_state_change_ts = time.time()
    last_screen_state    = "ON"

    # STARTUP event — debounced (persisted to disk) so crash-restart loops
    # don't flood the event feed with hundreds of STARTUP entries.
    try:
        username = _get_active_username()
        if not _startup_is_debounced():
            _log_event("STARTUP", username)
            _stamp_startup()
        else:
            log("INFO", "activity: STARTUP debounced — skipping duplicate")
        last_user = username
    except Exception as e:
        log("WARN", f"activity_collection_loop startup init error: {e}")
        last_user = "SYSTEM"

    # Screen state callback — safe: runs in daemon thread, errors are non-fatal
    def on_screen_state(state: str):
        nonlocal last_screen_state
        try:
            current_user = _get_active_username()
            if state != last_screen_state:
                _log_event(f"SCREEN_{state}", current_user)
                last_screen_state = state
                log("INFO", f"activity: SCREEN_{state} for {current_user}")
        except Exception as e:
            log("WARN", f"on_screen_state error: {e}")

    try:
        screen_thread = _ScreenMonitorThread(on_screen_state)
        screen_thread.start()
    except BaseException as e:
        log("WARN", f"ScreenMonitorThread failed to start: {e}")

    while True:
        try:
            time.sleep(POLL_INTERVAL_SECONDS)
            now          = time.time()
            current_user = _get_active_username()

            # ── LOGIN / LOGOUT ────────────────────────────────────────────────
            if current_user != last_user:
                if last_user and last_user != "SYSTEM":
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("LOGOUT", last_user, dur)
                if current_user and current_user != "SYSTEM":
                    _log_event("LOGIN", current_user)
                    log("INFO", f"activity: LOGIN {current_user}")
                last_user            = current_user
                last_state           = "ACTIVE"
                last_state_change_ts = now
                continue

            if not current_user or current_user == "SYSTEM":
                continue  # No interactive user — nothing to track

            # ── LOCK / UNLOCK ─────────────────────────────────────────────────
            is_locked = _is_screen_locked()

            if is_locked:
                if last_state != "LOCK":
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("LOCK", current_user, dur)
                    log("INFO", f"activity: LOCK {current_user}")
                    last_state           = "LOCK"
                    last_state_change_ts = now
                else:
                    # ── Periodic LOCK heartbeat every 5 seconds ───────────────
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("LOCK", current_user, dur)
            else:
                if last_state == "LOCK":
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("UNLOCK", current_user, dur)
                    log("INFO", f"activity: UNLOCK {current_user}")
                    last_state           = "ACTIVE"
                    last_state_change_ts = now

                # ── IDLE / ACTIVE ─────────────────────────────────────────────
                idle_secs = _get_last_input_idle_seconds()
                is_idle   = idle_secs >= IDLE_THRESHOLD_SECONDS

                if is_idle and last_state == "ACTIVE":
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("IDLE", current_user, dur)
                    last_state           = "IDLE"
                    last_state_change_ts = now

                elif is_idle and last_state == "IDLE":
                    # ── Periodic IDLE heartbeat every 5 seconds ───────────────
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("IDLE", current_user, dur)

                elif not is_idle and last_state == "IDLE":
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("ACTIVE", current_user, dur)
                    log("INFO", f"activity: ACTIVE {current_user}")
                    last_state           = "ACTIVE"
                    last_state_change_ts = now

                else:
                    # ── Periodic ACTIVE heartbeat every 5 seconds ─────────────
                    dur = format_duration(int(now - last_state_change_ts))
                    _log_event("ACTIVE", current_user, dur)

        except BaseException as e:
            log("WARN", f"activity_collection_loop error: {e}")


def _on_shutdown():
    """Emit SHUTDOWN event when the process exits."""
    try:
        username = _get_active_username()
        _log_event("SHUTDOWN", username)
        log("INFO", "activity: SHUTDOWN logged")
    except Exception:
        pass


# ── Sync Loop (used by SyncService) ──────────────────────────────────────────

def activity_sync_loop(server_url: str):
    """
    Reads unsynced events from the local DB and uploads them to the portal API.
    Wakes immediately when _sync_now is set (state-change events), otherwise
    runs on a SYNC_INTERVAL_SECONDS cadence. Called from syncservice.py.
    """
    time.sleep(5)  # Stagger startup to let collection loop settle
    while True:
        try:
            events, ids = get_unsynced(limit=100)
            if events:
                meta    = _get_device_meta()
                payload = {
                    "device": meta["machine"],
                    "serial": meta["serial"],
                    "events": events,
                }
                resp = network.api_call(server_url, "POST", "/api/activity/upload", payload)
                if resp:
                    delete_synced(ids)
                    log("INFO", f"activity_sync: uploaded {len(events)} events")
                else:
                    log("WARN", "activity_sync: upload failed — will retry next cycle")
        except Exception as e:
            log("WARN", f"activity_sync_loop error: {e}")

        # Wait up to SYNC_INTERVAL_SECONDS, but wake early if a state-change
        # event signals _sync_now (gives near-real-time portal updates).
        _sync_now.wait(timeout=SYNC_INTERVAL_SECONDS)
        _sync_now.clear()


# ── Entry points (called from standalone service scripts) ─────────────────────

def start_activity_service():
    """Entry point for SentraGuardActivityService (activityservice.exe)."""
    init_db()
    atexit.register(_on_shutdown)
    _start_input_listeners()          # Start pynput mouse + keyboard counters
    _AppUsageThread().start()         # Start 30s foreground-app sampler
    log("INFO", "SentraGuardActivityService started")
    activity_collection_loop()        # Blocks indefinitely


def start_sync_service(server_url: str):
    """Entry point for SentraGuardSyncService (syncservice.exe)."""
    init_db()
    log("INFO", f"SentraGuardSyncService started — server: {server_url}")
    activity_sync_loop(server_url)  # Blocks indefinitely


# ── Legacy: threaded integration from agent.py ────────────────────────────────

def start_activity_tracker_loop(server_url: str):
    """
    Backward-compat entry point — starts both loops as daemon threads
    inside agent.exe. Kept for fallback/dev use.
    """
    init_db()
    atexit.register(_on_shutdown)
    threading.Thread(target=activity_collection_loop, daemon=True, name="ActivityCollection").start()
    threading.Thread(target=activity_sync_loop, args=(server_url,), daemon=True, name="ActivitySync").start()
