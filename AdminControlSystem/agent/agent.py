"""
Admin Control System — Agent
Installed on company PCs. Polls the central server for commands,
executes them locally, and reports results.

Run with administrator privileges:
    python agent.py --server http://SERVER_IP:8000

Optional:  --dry-run   (prints commands instead of executing them)
"""

import argparse
import json
import platform
import os
import socket
import ctypes
from ctypes import wintypes
HAS_PYWINPTY = False
try:
    from winpty import PtyProcess, Backend
    HAS_PYWINPTY = True
except ImportError:
    try:
        from pywinpty import PtyProcess, Backend
        HAS_PYWINPTY = True
    except ImportError:
        pass
import subprocess
import sys
import time
import threading
import asyncio
import hashlib
import random
import secrets
import string
import tempfile
import shutil
import ssl
from pathlib import Path
from datetime import datetime
from urllib import request, error, parse
import http.client
from typing import Optional, Dict, List, cast

import psutil  # type: ignore
import websockets  # type: ignore

# Windows-specific creation flags (fallback to 0 for static analyzers / non-Win envs)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CREATE_DEFAULT_ERROR_MODE = getattr(subprocess, "CREATE_DEFAULT_ERROR_MODE", 0)
WINDLL = getattr(ctypes, "windll", None)


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # pyre-ignore[16]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # pyre-ignore[16]
    except Exception:
        pass

if sys.platform == "win32" and WINDLL:
    try:
        hwnd = WINDLL.kernel32.GetConsoleWindow()
        if hwnd:
            WINDLL.user32.ShowWindow(hwnd, 0) # SW_HIDE
        # Suppress Windows error dialog boxes for child processes (e.g., broken PowerShell)
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        SEM_NOOPENFILEERRORBOX = 0x8000
        WINDLL.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
    except Exception:
        pass


def is_admin():
    """Check if the agent is running with Administrator privileges."""
    try:
        if not WINDLL:
            return False
        return WINDLL.shell32.IsUserAnAdmin() != 0  # type: ignore
    except:
        return False

# ── Configuration ───────────────────────────────────────────────────────────

AGENT_VERSION = "1.1.19"
SERVICE_NAME = "YourAgent"
DEFAULT_INSTALL_DIR = r"C:\\Program Files\\YourAgent"
STATE_FILE = "agent_state.json"
UPDATE_STAGING_DIR = "updates"
SWAP_LOCK_FILE = "agent_swap.lock"
NOTIFY_QUEUE_FILE = "notify_queue.json"
UPDATE_MIN_INTERVAL = 5  # seconds (reduced for testing)
UPDATE_MAX_INTERVAL = 10  # seconds (reduced for testing)
WATCHDOG_INTERVAL = 8      # seconds

POLL_INTERVAL = 5  # seconds
LOG_COLLECT_INTERVAL = 60  # seconds — how often to collect event logs
SOFTWARE_REFRESH_INTERVAL = 600  # seconds — refresh installed software inventory
ACTIVITY_INTERVAL = 15  # seconds — user activity sampling

# Cache to avoid repeatedly asking for BitLocker keys (which takes 5s per drive)
_recovery_keys_cache = {}

# ── Event Log Collector ────────────────────────────────────────────────────

# Maps (log_source) → list of Event IDs to collect
EVENT_LOG_FILTERS = {
    'Security': [
        4624, 4625, 4634, 4647, 4648, 4675,         # Authentication
        4768, 4769, 4770, 4771, 4776,               # Kerberos/NTLM
        4672, 4673, 4674, 4964,                     # Privilege
        4688, 4689, 4696,                           # Process
        4656, 4663, 4658, 4670,                     # Object Access
        4720, 4722, 4723, 4724, 4725, 4726,         # Account Management
        4727, 4728, 4729, 4732, 4733, 4735, 4756, 4757, # Group Management
        4778, 4779, 4800, 4801,                     # Session
        4798, 4799,                                 # Enumeration
        4719, 4739, 4902, 4907,                     # Policy Change
        4608, 4609, 4616, 1102,                     # System / Tampering
        5379
    ],
    'System': [1074, 1, 41, 6005, 6006, 6008, 6009, 7001, 7002, 10000, 10001, 10002, 10100],
    'Application': [1000, 1001, 1002, 11, 7, 51, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 24, 50]
}

# Mapping of Event IDs to human-readable names
EVENT_ID_NAMES = {
    # Security log - Authentication
    4624: 'login_success', 4625: 'login_failed', 4634: 'logoff', 
    4647: 'user_logoff', 4648: 'logon_explicit_creds', 4675: 'sids_filtered',
    # Security log - Kerberos/NTLM
    4768: 'kerberos_ticket_req', 4769: 'kerberos_service_req', 4770: 'kerberos_ticket_renew',
    4771: 'kerberos_preauth_failed', 4776: 'ntlm_auth',
    # Security log - Privilege
    4672: 'special_privs_assigned', 4673: 'priv_service_call', 4674: 'priv_obj_access', 4964: 'special_groups_assigned',
    # Security log - Process
    4688: 'process_creation', 4689: 'process_termination', 4696: 'process_token_assigned',
    # Security log - Object Access
    4656: 'handle_requested', 4663: 'object_accessed', 4658: 'handle_closed', 4670: 'permissions_changed',
    # Security log - Account & Group Management
    4720: 'user_created', 4722: 'user_enabled', 4723: 'password_change_attempt',
    4724: 'password_reset_attempt', 4725: 'user_disabled', 4726: 'user_deleted',
    4727: 'security_group_created', 4728: 'member_added_global', 4729: 'member_removed_global',
    4732: 'member_added_local', 4733: 'member_removed_local', 4735: 'security_group_modified',
    4738: 'user_account_changed', 4756: 'member_added_global', 4757: 'member_removed_global', 5379: 'user_account_management',
    # Security log - Session & Enumeration
    4778: 'session_reconnected', 4779: 'session_disconnected', 4800: 'workstation_locked', 4801: 'workstation_unlocked',
    4798: 'user_group_enum', 4799: 'sec_group_enum',
    # Security log - Policy & System & Tampering
    4719: 'audit_policy_changed', 4739: 'domain_policy_changed', 4902: 'per_user_audit_changed', 4907: 'obj_auditing_changed',
    4608: 'windows_starting', 4609: 'windows_shutting_down', 4616: 'system_time_changed', 1102: 'audit_log_cleared',
    
    5156: 'connection_allowed', 5157: 'connection_blocked',
    # System log
    1074: 'system_shutdown_restart', 1: 'system_start', 41: 'kernel_power_error',
    6005: 'event_log_started', 6006: 'event_log_stopped', 6008: 'unexpected_shutdown',
    6009: 'system_version_info', 7001: 'service_start_success', 7002: 'service_start_failure',
    10000: 'wlan_connected', 10001: 'wlan_disconnected', 10002: 'wlan_error',
    10100: 'generic_system_error',
    # Application log
    1000: 'app_crash', 1001: 'error_reporting', 1002: 'app_hang', 11: 'disk_error',
    7: 'disk_controller_error', 51: 'disk_warning', 12: 'driver_init_failure',
}

EVENT_STATE_FILE = "event_state.json"

EVENT_STATE_FILE = "event_state.json"


class EventLogCollector:
    """Collects Windows Event Logs using PowerShell Get-WinEvent."""

    def __init__(self, server_url, device_id, hostname):
        self.server_url = server_url
        self.device_id = device_id
        self.hostname = hostname
        self.state = self._load_state()
        self.retry_batch = []  # events that failed to send last round

    def _state_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), EVENT_STATE_FILE)

    def _load_state(self):
        try:
            with open(self._state_path(), 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        try:
            with open(self._state_path(), 'w') as f:
                json.dump(self.state, f)
        except Exception as e:
            log('WARN', f"Failed to save event state: {e}")

    def collect_and_send(self):
        """One full collection cycle: query logs, batch, POST to server."""
        all_events = list(self.retry_batch)  # start with any failed events
        self.retry_batch = []

        for log_source, event_ids in EVENT_LOG_FILTERS.items():
            try:
                events = self._query_log(log_source, event_ids)
                all_events.extend(events)
            except Exception as e:
                log('WARN', f"Failed to collect {log_source} logs: {e}")

        if not all_events:
            return

        log('INFO', f"📋 Collected {len(all_events)} event log(s), sending to server…")

        payload = {
            "device_id": self.device_id,
            "logs": all_events
        }

        resp = api_call(self.server_url, 'POST', '/api/v1/device/logs', payload)
        if resp and resp.get('status') == 'ok':
            log('INFO', f"✓ Sent {resp.get('inserted', 0)} event logs to server")
            self._save_state()
        else:
            log('WARN', f"Failed to send event logs, will retry next cycle ({len(all_events)} events)")
            self.retry_batch = all_events

    def _query_log(self, log_source, event_ids):
        """Use PowerShell Get-WinEvent to retrieve events since last timestamp."""
        if not powershell_available():
            log('WARN', f"Skipping {log_source} event collection: PowerShell unavailable.")
            return []
        last_ts = self.state.get(log_source, "")
        event_ids_set = set(event_ids)
        start_clause = f"; StartTime=(Get-Date '{last_ts}')" if last_ts else ""

        # For Security log: query broadly WITHOUT Id filter, then filter in Python.
        # PowerShell's FilterHashtable fails with many IDs (returns "No events found").
        if log_source == "Security":
            ps_command = (
                f"Get-WinEvent -FilterHashtable @{{LogName='Security'{start_clause}}} -MaxEvents 200 -ErrorAction Stop | "
                f"ForEach-Object {{ @{{ Id=$_.Id; LogName=$_.LogName; "
                f"TimeCreated=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
                f"Message=$_.Message; "
                f"Username=$(if ($_.Properties.Count -gt 5) {{ $_.Properties[5].Value }} else {{ $_.UserId }}) "
                f"}} | ConvertTo-Json -Compress }}"
            )
        else:
            ids_csv = ",".join(str(eid) for eid in event_ids)
            ps_command = (
                f"Get-WinEvent -FilterHashtable @{{LogName='{log_source}'; Id={ids_csv}{start_clause}}} -MaxEvents 100 -ErrorAction Stop | "
                f"ForEach-Object {{ @{{ Id=$_.Id; LogName=$_.LogName; "
                f"TimeCreated=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
                f"Message=$_.Message; "
                f"Username=$_.UserId "
                f"}} | ConvertTo-Json -Compress }}"
            )

        if log_source == "Security":
            log('DEBUG', f"Querying Security log (broad, filter in Python)…")

        try:
            result = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-NonInteractive', '-Command', ps_command],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                err = result.stderr.strip()
                if "No events were found" in err:
                    return []
                if "Access is denied" in err and log_source == "Security":
                    log('ERROR', "Permission denied: Cannot read Security log. Please RUN AGENT AS ADMINISTRATOR.")
                    return []
                log('ERROR', f"PowerShell {log_source} failed: {err[:300]}")  # type: ignore
                raise Exception(err)

            stdout = result.stdout.strip()
            if not stdout:
                return []

            lines = stdout.split('\n')
            events = []
            newest_ts = last_ts

            for line in lines:
                if not line.strip(): continue
                try:
                    evt = json.loads(line)
                except: continue

                eid = evt.get('Id')

                # For Security log: filter by our target Event IDs in Python
                if log_source == "Security" and eid not in event_ids_set:
                    continue

                ts_str = evt.get('TimeCreated')
                raw_user = evt.get('Username')
                uname = str(raw_user) if raw_user is not None and str(raw_user).strip() != "" else None

                events.append({
                    "event_id": eid,
                    "event_name": EVENT_ID_NAMES.get(eid, f"event_{eid}"),
                    "log_source": log_source,
                    "timestamp": ts_str,
                    "username": uname,
                    "hostname": self.hostname,
                    "message": (str(evt.get('Message') or ''))[:500],  # type: ignore
                })

                if not newest_ts or ts_str > newest_ts:
                    newest_ts = ts_str

            if newest_ts:
                self.state[log_source] = newest_ts  # type: ignore

            if log_source == "Security":
                log('INFO', f"📋 Security: found {len(events)} matching events out of {len(lines)} raw events")

            return events

        except subprocess.TimeoutExpired:
            log('WARN', f"Get-WinEvent timed out for {log_source}")
            return []
        except Exception as e:
            log('WARN', f"Error querying {log_source}: {str(e)[:200]}")  # type: ignore
            return []


def event_log_collector_thread(server_url, device_id, hostname):
    """Background thread that runs the EventLogCollector on a timer."""
    collector = EventLogCollector(server_url, device_id, hostname)
    log('INFO', f"📋 Event Log Collector started (interval: {LOG_COLLECT_INTERVAL}s)")
    while True:
        try:
            collector.collect_and_send()
        except Exception as e:
            log('ERROR', f"Event log collection error: {e}")
        time.sleep(LOG_COLLECT_INTERVAL)


def software_inventory_thread(server_url, device_id):
    """Background thread that periodically sends installed software inventory."""
    log('INFO', f"📦 Software inventory sync started (interval: {SOFTWARE_REFRESH_INTERVAL}s)")
    # Send one immediate snapshot on start
    try:
        push_software_inventory(server_url, device_id)
    except Exception as e:
        log('WARN', f"Initial software inventory failed: {e}")

    while True:
        try:
            push_software_inventory(server_url, device_id)
        except Exception as e:
            log('WARN', f"Software inventory error: {e}")
        time.sleep(SOFTWARE_REFRESH_INTERVAL)

# ── Helpers ─────────────────────────────────────────────────────────────────

def log(level, message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}]  {message}"
    print(line, flush=True)
    try:
        # Determine log path safely
        exe_dir = Path(os.path.dirname(os.path.abspath(sys.executable)))
        log_path = Path(os.environ.get("TEMP", ".")) / "agent_debug.log"
        
        # If we are in Program Files, try to write there (usually requires admin)
        if "Program Files" in str(exe_dir):
            log_path = exe_dir / "agent_debug.log"
            
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass


# ── Path & state helpers ────────────────────────────────────────────────────

def runtime_root() -> Path:
    """Return the directory that contains the running binary or script."""
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def state_file_path() -> Path:
    return runtime_root() / STATE_FILE


def notify_queue_path() -> Path:
    """Queue file lives in ProgramData so both service (SYSTEM) and users can access it."""
    base = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData")) / "YourAgent"
    try:
        base.mkdir(parents=True, exist_ok=True)
        # Grant Users modify rights so a standard user session can pop items
        subprocess.run(
            ["icacls", str(base), "/grant", "Users:(OI)(CI)M", "/T", "/Q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )
    except Exception:
        pass
    return base / NOTIFY_QUEUE_FILE


def load_state() -> dict:
    try:
        with open(state_file_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(data: dict):
    try:
        state_file_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log("WARN", f"Could not persist agent state: {e}")


def update_state(**kwargs):
    state = load_state()
    state.update(kwargs)
    save_state(state)


def enqueue_notification(message: str):
    """Persist a notification so a user-session tray process can display it."""
    try:
        path = notify_queue_path()
        queue = []
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


def dequeue_notification() -> str | None:
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


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


# Global SSL context and auth token (set at startup based on CLI flags)
_ssl_context = None
AGENT_AUTH_TOKEN = None
PINNED_CERT_SHA256 = None
LAST_SYNC_TS = None
_POWERSHELL_OK: bool | None = None
_POWERSHELL_LAST_CHECK: float = 0.0  # timestamp of last check
_POWERSHELL_CACHE_TTL: float = 60.0  # re-check every 60 seconds


def _check_cert_pin(response):
    """Optional certificate pinning: compare SHA256 fingerprint of server cert."""
    if not PINNED_CERT_SHA256:
        return
    try:
        cert_bin = response.fp.raw._sock.getpeercert(binary_form=True)  # type: ignore[attr-defined]
        fp = hashlib.sha256(cert_bin).hexdigest().lower()
        if fp != PINNED_CERT_SHA256.lower():
            raise ValueError(f"TLS pin mismatch: expected {PINNED_CERT_SHA256}, got {fp}")
    except Exception as e:
        log("ERROR", f"Certificate pinning failed: {e}")
        raise


def powershell_available() -> bool:
    """Lightweight check to avoid crashing dialogs when PowerShell is broken.
    Re-checks every 60 seconds so a transient failure doesn't permanently disable PS."""
    global _POWERSHELL_OK, _POWERSHELL_LAST_CHECK
    now = time.time()
    if _POWERSHELL_OK is not None and (now - _POWERSHELL_LAST_CHECK) < _POWERSHELL_CACHE_TTL:
        return _POWERSHELL_OK
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', 'exit'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE,
            timeout=5,
        )
        _POWERSHELL_OK = result.returncode == 0
    except Exception:
        _POWERSHELL_OK = False
    _POWERSHELL_LAST_CHECK = now
    if not _POWERSHELL_OK:
        log('WARN', "PowerShell unavailable or failing to start; related features disabled.")
    return _POWERSHELL_OK


def api_call(base_url, method, path, body=None, headers=None, timeout=15):
    """Simple HTTP helper using only urllib (no external deps)."""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode('utf-8') if body else None
    req = request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Agent-Version', AGENT_VERSION)
    if AGENT_AUTH_TOKEN:
        req.add_header('Authorization', f"Bearer {AGENT_AUTH_TOKEN}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context) as res:
            _check_cert_pin(res)
            return json.loads(res.read().decode('utf-8'))
    except error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        log('ERROR', f"API {method} {path} → {e.code}: {detail}")
        return None
    except http.client.RemoteDisconnected as e:
        log('ERROR', f"Remote end closed connection without response. (Hint: check if you are connecting via HTTP to an HTTPS port or vice-versa.) Details: {e}")
        return None
    except error.URLError as e:
        if "certificate verify failed" in str(e).lower():
            log('ERROR', f"SSL certificate verification failed: {e}. (Hint: Use --no-verify-ssl if the server is using a self-signed certificate.)")
        else:
            log('ERROR', f"Cannot reach server: {e.reason}")
        return None


def current_binary_path() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()


def resolve_install_root(cli_install_dir: str | None = None) -> Path:
    """Decide where the agent considers its home/install directory."""
    if cli_install_dir:
        return Path(cli_install_dir)
    env_dir = os.environ.get("ACS_INSTALL_DIR")
    if env_dir:
        return Path(env_dir)
    runtime = runtime_root()
    if "Program Files" in str(runtime):
        return runtime
    return Path(DEFAULT_INSTALL_DIR)


def staging_dir_path(install_root: Path) -> Path:
    path = install_root / UPDATE_STAGING_DIR
    ensure_dir(path)
    return path


def is_service_running(name: str) -> bool:
    try:
        out = subprocess.check_output(["sc", "query", name], creationflags=CREATE_NO_WINDOW)
        return b"RUNNING" in out
    except Exception:
        return False


def stop_service(name: str):
    cmds = [
        ["nssm", "stop", name],
        ["sc", "stop", name],
    ]
    for cmd in cmds:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except Exception:
            continue


def restart_service(name: str):
    cmds = [
        ["nssm", "restart", name],
        ["sc", "start", name],
    ]
    for cmd in cmds:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            if is_service_running(name):
                return
        except Exception:
            continue


def download_binary(url: str, dest_path: Path):
    """Download binary content to path with optional auth + pinning and progress logging."""
    req = request.Request(url)
    if AGENT_AUTH_TOKEN:
        req.add_header("Authorization", f"Bearer {AGENT_AUTH_TOKEN}")
    req.add_header("X-Agent-Version", AGENT_VERSION)
    with request.urlopen(req, timeout=60, context=_ssl_context) as res:
        _check_cert_pin(res)

        # Stream the download to report progress
        total_size = int(res.getheader('Content-Length', 0))
        ensure_dir(dest_path.parent)

        CHUNK_SIZE = 1048576  # 1 MB
        downloaded: int = 0
        last_reported_pct: int = 0

        with open(dest_path, 'wb') as f:
            while True:
                chunk = res.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                
                if total_size > 0:
                    pct = int((downloaded / total_size) * 100)
                    # Report every 20%
                    if pct - last_reported_pct >= 20 or pct == 100:
                        log("INFO", f"⬇ Downloading update: {pct}% ({downloaded // 1048576} MB / {total_size // 1048576} MB)")
                        last_reported_pct = pct

    return dest_path


def schedule_binary_swap(staged_path: Path, service_name: str):
    """Swap the current binary with the staged one via a detached PowerShell helper."""
    target = current_binary_path()
    backup = target.with_name(f"{target.stem}_old_{int(time.time())}{target.suffix}")
    helper = staged_path.with_suffix(".ps1")
    
    script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
$source = '{staged_path}'
$target = '{target}'
$backup = '{backup}'
$service = '{service_name}'
$procName = [System.IO.Path]::GetFileNameWithoutExtension($target)

# Clean up ANY older backup files to save disk space
Write-Output "Cleaning up previous backups..."
Get-ChildItem (Split-Path $target) -Filter "$procName`_old_*" | ForEach-Object {{
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}}

# Stop service + any stray agent processes to release file locks
Write-Output "Stopping service $service..."
Stop-Service -Name $service -Force -ErrorAction SilentlyContinue
Get-Process -Name $procName -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "$procName`_old_*" -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Output "Swapping binary..."
$copied = $false
for ($i = 0; $i -lt 10; $i++) {{
    try {{
        Start-Sleep -Seconds 1
        # Backup running binary
        Copy-Item $target $backup -Force
        # Place new binary
        Copy-Item $source $target -Force
        $copied = $true
        break
    }} catch {{
        Start-Sleep -Seconds 1
    }}
}}

if ($copied) {{
    Write-Output "Starting binary / service..."
    if (Get-Service -Name $service -ErrorAction SilentlyContinue) {{
        Start-Service -Name $service -ErrorAction SilentlyContinue
    }} else {{
        # Fallback to direct execution
        Start-Process -FilePath $target
    }}
}}

Remove-Item $source -Force -ErrorAction SilentlyContinue
Remove-Item $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
    try:
        helper.write_text(script, encoding="utf-8")
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        log("INFO", "Update helper launched; exiting for binary swap…")
        os._exit(0)
    except Exception as e:
        log("ERROR", f"Failed to launch update helper: {e}")



def update_poll_loop(server_url: str, device_id: str, service_name: str, install_root: Path):
    """Background loop that checks for newer agent versions and applies them safely."""
    staging = staging_dir_path(install_root)
    while True:
        wait_s = random.randint(UPDATE_MIN_INTERVAL, UPDATE_MAX_INTERVAL)
        time.sleep(wait_s)
        try:
            resp_data = api_call(server_url, "GET", f"/agent/version?device_id={device_id}&current_version={AGENT_VERSION}")
            if not isinstance(resp_data, dict) or not resp_data.get("update_available"):
                continue
            
            download_url = cast(str, resp_data.get("download_url"))
            checksum = cast(str, resp_data.get("checksum_sha256"))
            new_version = cast(str, resp_data.get("version"))
            if not download_url or not new_version:
                continue

            file_name = download_url.split("/")[-1].split("?")[0] or f"agent-{new_version}.exe"
            staged_path = staging / file_name
            log("INFO", f"⬇ Downloading agent update {new_version}…")
            download_binary(download_url, staged_path)
            if checksum:
                actual = compute_sha256(staged_path)
                if actual.lower() != checksum.lower():
                    log("ERROR", f"Checksum mismatch for update: expected {checksum}, got {actual}")
                    staged_path.unlink(missing_ok=True)
                    continue
            log("INFO", f"Update {new_version} ready; scheduling binary swap.")
            schedule_binary_swap(staged_path, service_name)
        except Exception as e:
            log("WARN", f"Version check/apply failed: {e}")


def start_watchdog_process(server_url: str, service_name: str):
    """Spawn a lightweight watchdog to restart the agent if killed."""
    try:
        exe = current_binary_path()
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        cmd = [
            str(exe),
            "--watchdog",
            f"--parent-pid={os.getpid()}",
            f"--server={server_url}",
            f"--service-name={service_name}",
        ]
        if AGENT_AUTH_TOKEN:
            cmd.append(f"--token={AGENT_AUTH_TOKEN}")
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        log("INFO", "Watchdog process spawned.")
    except Exception as e:
        log("WARN", f"Failed to start watchdog: {e}")


def watchdog_loop(parent_pid: int, service_name: str, server_url: str):
    """Runs in watchdog mode."""
    log("INFO", f"Watchdog guarding PID {parent_pid}")
    install_root = current_binary_path().parent
    lock_file = install_root / SWAP_LOCK_FILE

    # Clean up any stale lock file from a previous failed swap attempt
    # (if the swap script crashed before removing the lock, we clear it here)
    if lock_file.exists():
        # Only clear it if parent is alive — if parent is already gone, the
        # swap helper is likely still running so we should respect the lock
        if parent_pid and psutil.pid_exists(parent_pid):
            try:
                lock_file.unlink()
                log("INFO", "Cleared stale swap lock file on watchdog startup.")
            except Exception:
                pass

    while True:
        if parent_pid and not psutil.pid_exists(parent_pid):
            # Check for swap lock before restarting
            if lock_file.exists():
                log("INFO", "Agent stopped but swap in progress. Watchdog idling...")
                time.sleep(WATCHDOG_INTERVAL * 2)
                continue

            log("WARN", "Primary agent stopped — attempting restart.")
            restart_service(service_name)
            if not is_service_running(service_name):
                try:
                    exe = current_binary_path()
                    cmd = [str(exe), "--server", server_url]
                    if AGENT_AUTH_TOKEN:
                        cmd.append(f"--token={AGENT_AUTH_TOKEN}")
                    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
                except Exception:
                    pass
            parent_pid = 0  # prevent tight loop
        time.sleep(WATCHDOG_INTERVAL)



def tamper_guard_loop(service_name: str):
    """Lightweight guard to restart service or restore binary if tampered."""
    binary = current_binary_path()
    backup = binary.with_name(f"{binary.stem}_backup{binary.suffix}")
    while True:
        time.sleep(max(WATCHDOG_INTERVAL, 10))
        try:
            if service_name and not is_service_running(service_name):
                restart_service(service_name)
            if not binary.exists() and backup.exists():
                shutil.copy2(backup, binary)
                log("WARN", "Agent binary restored from backup after deletion attempt.")
        except Exception:
            pass


def protected_uninstall_flow(server_url: str, otp: str | None, service_name: str, install_root: Path, verify_only: bool = False):
    """Verify OTP with backend and uninstall service + files."""
    state = load_state()
    device_id = state.get("device_id")

    if not device_id:
        # Best-effort re-registration to retrieve device id
        resp = api_call(server_url, "POST", "/register", {
            "hostname": get_hostname(),
            "ip_address": get_ip(),
            "agent_version": AGENT_VERSION,
            "install_path": str(install_root),
        })
        if resp and resp.get("device_id"):
            device_id = resp["device_id"]
            update_state(device_id=device_id)

    if not device_id:
        log("ERROR", "Cannot determine device ID; uninstall aborted.")
        return False

    if otp:
        code = otp.strip()
    else:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        code = simpledialog.askstring("Uninstall Authorization", "Enter uninstall OTP from admin portal:")
        
    if not code:
        log("ERROR", "OTP is required for uninstall.")
        return False

    resp = api_call(server_url, "POST", "/verify-uninstall", {
        "device_id": device_id,
        "otp": code,
        "hostname": get_hostname(),
    })
    if not resp or resp.get("status") != "ok":
        detail = resp.get("detail") if resp else "No response from server"
        log("ERROR", f"Uninstall blocked: invalid or expired OTP. {detail}")
        return False

    if verify_only:
        log("INFO", "OTP validated successfully. (verify_only=True)")
        return True

    log("INFO", "OTP validated. Stopping service and removing files…")
    stop_service(service_name)
    try:
        safe_root = str(install_root).lower()
        if "youragent" in safe_root:
            if not powershell_available():
                log("WARN", "PowerShell unavailable; using Python fallback for uninstall cleanup.")
                # 1) Kill processes
                for proc_name in ["agent.exe", "agent", "nssm.exe", "nssm"]:
                    try:
                        subprocess.run(["taskkill", "/F", "/IM", proc_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
                    except Exception:
                        pass
                time.sleep(3)  # Wait for processes to fully terminate
                # 2) Delete service via sc
                try:
                    subprocess.run(["sc", "stop", service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
                    time.sleep(2)
                    subprocess.run(["sc", "delete", service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
                except Exception:
                    pass
                # 3) Remove install dir with retries
                for attempt in range(5):
                    try:
                        if install_root.exists():
                            shutil.rmtree(install_root, ignore_errors=True)
                        if not install_root.exists():
                            break
                        time.sleep(3)
                    except Exception as e:
                        log("WARN", f"Failed to remove install dir (attempt {attempt+1}): {e}")
                        time.sleep(3)
                # 4) Clean registry
                try:
                    import winreg
                    for hive, path in [
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\YourAgent"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\YourAgent"),
                    ]:
                        try:
                            winreg.DeleteKey(winreg.ConnectRegistry(None, hive), path)
                        except Exception:
                            pass
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                        winreg.DeleteValue(key, "YourAgentTray")
                        key.Close()
                    except Exception:
                        pass
                except Exception as e:
                    log("WARN", f"Registry cleanup fallback failed: {e}")
            else:
                ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
# 1. Stop and Delete Windows Service
Stop-Service -Name "{service_name}" -Force
sc.exe stop "{service_name}"
Start-Sleep -Seconds 2
sc.exe delete "{service_name}"

# 2. Kill all related processes
$procs = @("agent", "nssm", "winpty-agent")
foreach ($p in $procs) {{
    Get-Process -Name $p -ErrorAction SilentlyContinue | Stop-Process -Force
}}

# 3. Wait for handles to release
Start-Sleep -Seconds 3

# 4. Remove installation directory with retries
for ($i=0; $i -lt 5; $i++) {{
    if (Test-Path "{install_root}") {{
        Remove-Item "{install_root}" -Recurse -Force
        if (!(Test-Path "{install_root}")) {{ break }}
        Start-Sleep -Seconds 3
    }} else {{ break }}
}}

# 5. Clean registry entries
Remove-Item -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\YourAgent" -Recurse -Force
Remove-Item -Path "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\YourAgent" -Recurse -Force
Remove-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" -Name "YourAgentTray" -ErrorAction SilentlyContinue
"""
                # Write script to temp file and run it (avoids cmd-line quoting issues)
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w', encoding='utf-8') as tf:
                    tf.write(ps_script)
                    ps_temp_path = tf.name

                log("INFO", f"Running uninstall cleanup script: {ps_temp_path}")
                try:
                    # Run synchronously with timeout so we know if cleanup succeeded
                    result = subprocess.run(
                        ['powershell', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ps_temp_path],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE,
                        timeout=60,
                    )
                    log("INFO", f"Uninstall script exited with code {result.returncode}")
                    if result.stderr:
                        log("DEBUG", f"Uninstall script stderr: {result.stderr.decode('utf-8', errors='replace')[:500]}")
                except subprocess.TimeoutExpired:
                    log("WARN", "Uninstall cleanup script timed out (60s) — cleanup may be incomplete.")
                except Exception as e:
                    log("WARN", f"Uninstall cleanup script error: {e}")
                finally:
                    try:
                        os.remove(ps_temp_path)
                    except Exception:
                        pass
        else:
            log("WARN", f"Install path '{install_root}' does not look safe to delete; skipped.")
    except Exception as e:
        log("WARN", f"Cleanup warning: {e}")
    log("INFO", "Agent uninstalled successfully.")
    return True


def get_hostname():
    return platform.node() or socket.gethostname()


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def collect_system_info():
    """Collect hardware & OS telemetry using a single PowerShell script.
    Returns a dict ready to be JSON-serialised and sent to the server.
    """
    if not powershell_available():
        # Minimal fallback info without PowerShell to avoid popup errors
        return {
            "os": platform.platform(),
            "hostname": get_hostname(),
            "ip": get_ip(),
        }
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'

# OS / Uptime
$os       = Get-WmiObject Win32_OperatingSystem
$upSec    = (New-TimeSpan -Start $os.ConvertToDateTime($os.LastBootUpTime) -End (Get-Date)).TotalSeconds
$upFmt    = "$([int]($upSec/3600))h $([int](($upSec%3600)/60))m"
$freeGB   = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totalGB  = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)

# CPU
$cpu      = Get-WmiObject Win32_Processor | Select-Object -First 1
$cpuLoad  = (Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average

# Disks & BitLocker
$disksRaw = Get-WmiObject Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $drive = $_.DeviceID
    $blRaw = manage-bde -status $drive 2>$null
    $bl = ($blRaw | Out-String)
    
    $perc = 'N/A'
    if ($bl -match 'Percentage Encrypted:\s+([\d\.]+\s*%)') { $perc = $matches[1].Trim() }
    
    $prot = 'Unknown'
    if ($bl -match 'Protection Status:\s+Protection\s+(On|Off)') { $prot = $matches[1] }
    elseif ($bl -match 'Protection Status:\s+(\w+)') { $prot = $matches[1] }

    $conv = 'Unknown'
    if ($bl -match 'Conversion Status:\s+(.+)') { $conv = $matches[1].Trim() }

    @{
        drive       = $drive
        size_gb     = [math]::Round($_.Size / 1GB, 2)
        free_gb     = [math]::Round($_.FreeSpace / 1GB, 2)
        bitlocker   = "$perc (Protection $prot)"
        bl_status   = $conv
    }
}

# Manufacturer / Model / User
$cs = Get-WmiObject Win32_ComputerSystem

# Network adapters (LAN & Wi-Fi, physical only)
$nics = Get-WmiObject Win32_NetworkAdapter -Filter "PhysicalAdapter=True and MACAddress IS NOT NULL" | ForEach-Object {
    $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "Index=$($_.Index)"
    $ip = $null
    if ($cfg -and $cfg.IPAddress) {
        $ip = ($cfg.IPAddress | Where-Object { $_ -notmatch ':' } | Select-Object -First 1)
    }
    @{
        description = $_.Name
        mac         = $_.MACAddress
        ip          = $ip
    }
}

# BIOS
$bios = Get-WmiObject Win32_BIOS

$result = @{
    hostname        = $env:COMPUTERNAME
    logged_user     = $cs.UserName
    os_name         = $os.Caption
    os_version      = $os.Version
    os_arch         = $os.OSArchitecture
    uptime          = $upFmt
    cpu_name        = $cpu.Name.Trim()
    cpu_cores       = $cpu.NumberOfCores
    cpu_load_pct    = $cpuLoad
    ram_total_gb    = $totalGB
    ram_free_gb     = $freeGB
    ram_used_pct    = [math]::Round((($totalGB - $freeGB) / $totalGB) * 100, 1)
    disks           = @($disksRaw)
    manufacturer    = $cs.Manufacturer
    model           = $cs.Model
    serial_number   = $bios.SerialNumber
    bios_version    = $bios.SMBIOSBIOSVersion
    network         = @($nics)
}

$result | ConvertTo-Json -Depth 4 -Compress
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            
            # --- Auto-fetch BitLocker Recovery Keys ---
            import re
            for disk in data.get('disks', []):
                drive = disk.get('drive', '')
                bl_status = str(disk.get('bitlocker', ''))
                
                # Check if drive is actually encrypted
                is_encrypted = 'Protection On' in bl_status or ('%' in bl_status and not bl_status.startswith('0%') and not bl_status.startswith('N/A'))
                
                if is_encrypted:
                    if drive not in _recovery_keys_cache:
                        log('INFO', f"Auto-fetching recovery key for {drive}...")
                        success, out = execute_get_bitlocker_key(drive)
                        if success:
                            # Extract 48-digit numerical password: "Password: \n 111111-222222-..."
                            match = re.search(r'Password:\s*([0-9-]{55})', out)
                            if match:
                                _recovery_keys_cache[drive] = match.group(1).strip()
                            else:
                                _recovery_keys_cache[drive] = "Key not found in output"
                        else:
                            _recovery_keys_cache[drive] = "Failed to fetch key"
                    
                    disk['recovery_key'] = _recovery_keys_cache.get(drive, "Not found")
                else:
                    disk['recovery_key'] = "Not Encrypted"

            log('INFO', f"✓ System info collected (CPU: {data.get('cpu_name','?')}, RAM: {data.get('ram_total_gb','?')} GB)")
            return data
        else:
            log('WARN', f"System info PowerShell failed: {result.stderr.strip()[:200]}")  # type: ignore
    except subprocess.TimeoutExpired:
        log('WARN', "System info collection timed out")
    except Exception as e:
        log('WARN', f"System info error: {e}")
    return None


def execute_get_bitlocker_key(drive_letter, dry_run=False):
    """Retrieve BitLocker recovery key for a drive using manage-bde."""
    if not drive_letter:
        return False, "Drive letter required"
    
    drive = drive_letter.strip().upper()
    if len(drive) == 1:
        drive += ':'
    elif not drive.endswith(':'):
        # might be "C:" already
        pass

    cmd = ['manage-bde', '-protectors', '-get', drive, '-type', 'RecoveryPassword']
    
    if dry_run:
        log('DRY-RUN', f"Would run: {' '.join(cmd)}")
        return True, "Dry-run: recovery key command would be executed"

    try:
        # Run with elevated privileges (admin check is done at agent start)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0:
            output = result.stdout
            log('INFO', f"✓ BitLocker key retrieved for {drive}")
            return True, output
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, f"BitLocker error: {err}"
    except Exception as e:
        log('WARN', f"execute_get_bitlocker_key error: {e}")
        return False, f"Execution error: {str(e)}"

# ── Commands ────────────────────────────────────────────────────────────────


def collect_all_users():
    """Collect all local user accounts using PowerShell Get-LocalUser.
    Returns a list of dicts: [{name, enabled}]
    """
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$users = Get-LocalUser | Select-Object Name, Enabled | ForEach-Object {
    @{ name = $_.Name; enabled = [bool]$_.Enabled }
}
@($users) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            # Ensure it's always a list
            if isinstance(data, dict):
                data = [data]
            return data or []
    except Exception as e:
        log('WARN', f"collect_all_users error: {e}")
    return []


def collect_installed_software():
    """Collect installed software from standard Windows uninstall registry hives."""
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
)

$apps = foreach ($path in $paths) {
    if (Test-Path $path) {
        Get-ChildItem $path | ForEach-Object {
            $name = $_.GetValue('DisplayName')
            if (-not $name) { return }

            $isSystem = $_.GetValue('SystemComponent')
            if ($isSystem -eq 1) { return }

            $parent = $_.GetValue('ParentKeyName')
            if ($parent) { return }

            $release = $_.GetValue('ReleaseType')
            if ($release -and $release -match 'Update|Hotfix') { return }

            [PSCustomObject]@{
                Name            = $name
                Version         = $_.GetValue('DisplayVersion')
                Publisher       = $_.GetValue('Publisher')
                InstallDate     = $_.GetValue('InstallDate')
                UninstallString = $_.GetValue('UninstallString')
            }
        }
    }
}

$apps | Where-Object { $_ } | Sort-Object Name, Version -Unique | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=40, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            cleaned = []
            for item in data or []:
                name = item.get('Name') or item.get('name')
                if not name:
                    continue
                cleaned.append({
                    "name": name,
                    "version": item.get('Version') or item.get('version'),
                    "publisher": item.get('Publisher') or item.get('publisher'),
                    "install_date": item.get('InstallDate') or item.get('install_date'),
                    "uninstall_string": item.get('UninstallString') or item.get('uninstall_string'),
                })
            return cleaned
    except Exception as e:
        log('WARN', f"collect_installed_software error: {e}")
    return []


def push_software_inventory(server, device_id):
    """Collect and push installed software inventory to the server."""
    items = collect_installed_software()
    payload = {
        "device_id": device_id,
        "items": items or [],
    }
    resp = api_call(server, 'POST', '/api/v1/device/software', payload)
    if resp and resp.get('status') == 'ok':
        log('INFO', f"✓ Sent software inventory ({resp.get('count', 0)} items)")
    else:
        log('WARN', "Failed to send software inventory")


# ── User Activity Tracking ────────────────────────────────────────────────

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

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

        # Title
        buf = ctypes.create_unicode_buffer(512)
        WINDLL.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        # PID -> process name
        pid = wintypes.DWORD()
        WINDLL.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = _get_process_name(pid.value)

        return title or None, proc_name or None
    except Exception as e:
        log('WARN', f"_get_foreground_window_info error: {e}")
        return None, None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]

_activity_counts = {"clicks": 0, "keys": 0}

def _start_input_listeners():
    """Start pynput background threads for click and key counts."""
    try:
        from pynput import mouse, keyboard
        def on_click(x, y, button, pressed):
            if pressed:
                _activity_counts["clicks"] += 1

        def on_press(key):
            _activity_counts["keys"] += 1

        mouse_listener = mouse.Listener(on_click=on_click)
        key_listener = keyboard.Listener(on_press=on_press)
        
        mouse_listener.start()
        key_listener.start()
        log('INFO', "Input listeners (pynput) started for activity tracking.")
    except Exception as e:
        log('WARN', f"Could not start activity pynput listeners: {e}")

def _get_idle_seconds():
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


def collect_activity_sample():
    """Collect a single user activity sample."""
    title, proc_name = _get_foreground_window_info()
    idle = _get_idle_seconds()
    clicks = _activity_counts["clicks"]
    keys = _activity_counts["keys"]
    
    # Reset counts for the next interval
    _activity_counts["clicks"] = 0
    _activity_counts["keys"] = 0
    
    from datetime import timezone
    import os
    now_dt = datetime.now(timezone.utc)
    now_str = str(now_dt.isoformat(timespec='milliseconds'))
    now_iso = f"{now_str}Z".replace("+00:00", "")
    
    # Get current username
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


def activity_sampler_thread(server, device_id):
    log('INFO', f"🧭 Activity sampler started (interval: {ACTIVITY_INTERVAL}s)")
    _start_input_listeners()
    while True:
        try:
            sample = collect_activity_sample()
            payload = {"device_id": device_id, "activities": [sample]}
            api_call(server, 'POST', '/api/v1/activity', payload)
        except Exception as e:
            log('WARN', f"Activity sampler error: {e}")
        time.sleep(ACTIVITY_INTERVAL)


def execute_create_user(username, password, dry_run=False):
    """Create a new local user account using PowerShell."""
    # We must construct a secure string for the password
    ps_cmd = f'$Password = ConvertTo-SecureString "{password}" -AsPlainText -Force; New-LocalUser -Name "{username}" -Password $Password -Description "Created via Admin Control System"'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]

    if dry_run:
        # Mask the password in logs
        safe_cmd = f'$Password = ConvertTo-SecureString "***" -AsPlainText -Force; New-LocalUser -Name "{username}" -Password $Password ...'
        log('DRY-RUN', f"Would run: {safe_cmd}")
        return True, "Dry-run mode (command not executed)"

    # Execute, but if it fails don't log the raw command so password doesn't leak in agent log
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"{'✓' if success else '✗'} Create user {username} → {output}")
        return success, output
    except Exception as e:
        return False, str(e)


def execute_grant(username, dry_run=False):
    """Add a user to the local Administrators group using PowerShell."""
    ps_cmd = f'Add-LocalGroupMember -Group "Administrators" -Member "{username}"'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]

    if dry_run:
        log('DRY-RUN', f"Would run: {ps_cmd}")
        return True, "Dry-run mode (command not executed)"

    return _run_cmd(cmd, ps_cmd)


def execute_revoke(username, dry_run=False):
    """Remove a user from the local Administrators group using PowerShell."""
    ps_cmd = f'Remove-LocalGroupMember -Group "Administrators" -Member "{username}" -Confirm:$false'
    cmd = ['powershell', '-NoProfile', '-Command', ps_cmd]

    if dry_run:
        log('DRY-RUN', f"Would run: {ps_cmd}")
        return True, "Dry-run mode (command not executed)"

    return _run_cmd(cmd, ps_cmd)


def execute_check(dry_run=False):
    """Get the list of local admin group members using net localgroup."""
    cmd = ['net', 'localgroup', 'Administrators']

    if dry_run:
        log('DRY-RUN', f"Would run: {' '.join(cmd)}")
        return True, "Dry-run mode", ['Administrator', 'DryRunUser']

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0

        members = []
        if success:
            in_members = False
            for line in result.stdout.strip().splitlines():
                if line.startswith('---'):
                    in_members = True
                    continue
                if in_members:
                    if not line or line.startswith('The command completed'):
                        break
                    members.append(line)

        log('INFO', f"Admin members: {members}")
        return success, output, members

    except subprocess.TimeoutExpired:
        return False, "Command timed out", []
    except Exception as e:
        return False, str(e), []


def execute_shell(payload, dry_run=False):
    """Execute an arbitrary PowerShell script block."""
    if dry_run:
        log('DRY-RUN', f"Would run shell payload:\n{payload}")
        return True, f"Dry-run mode. Payload length: {len(payload)}"

    assert isinstance(payload, str)
    cmd_list: List[str] = ['powershell', '-NoProfile', '-NonInteractive', '-Command', payload]
    try:
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"Shell exec -> returncode {result.returncode}")
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Shell command timed out (max 60s)"
    except Exception as e:
        return False, str(e)


def execute_uninstall(payload, dry_run=False):
    """Uninstall software using the provided uninstall string from the registry."""
    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = {"uninstall_string": payload}

    uninstall_cmd = data.get('uninstall_string') or data.get('command')
    name = data.get('name') or 'target software'

    if not uninstall_cmd:
        return False, "No uninstall command provided by portal/agent"

    # Make a best-effort to run silently if possible
    cmd_to_run = uninstall_cmd.strip()
    lower_cmd = cmd_to_run.lower()

    def has_silent_flag(cmd: str) -> bool:
        flags = ['/qn', '/quiet', '/q', '/s', '/silent', '/verysilent', '/passive']
        return any(f in cmd.lower() for f in flags)

    def split_path_args(cmd: str):
        cmd = cmd.strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            exe = cmd[1:end] if end != -1 else cmd.strip('"')
            rest = cmd[end + 1:].strip() if end != -1 else ''
        else:
            parts = cmd.split(' ', 1)
            exe = parts[0]
            rest = parts[1] if len(parts) > 1 else ''
        return exe, rest

    exe, args = split_path_args(cmd_to_run)

    if 'msiexec' in exe.lower():
        # Ensure uninstall with quiet flags
        if (' /i' in args.lower()) and (' /x' not in args.lower()):
            args = args.replace('/I', '/X').replace('/i', '/x')
        if not has_silent_flag(args):
            args = args + ' /qn /norestart'
        exe = 'msiexec.exe'
    else:
        if not has_silent_flag(args):
            args = args + ' /S /VERYSILENT /silent /quiet /norestart'
        if '/s' not in args.lower():
            args = args + ' /S'

    # Build PowerShell Start-Process to avoid cmd quoting issues and hide window
    def ps_quote(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    ps_cmd = (
        f"Start-Process -FilePath {ps_quote(exe)} "
        f"-ArgumentList {ps_quote(args.strip())} "
        f"-WindowStyle Hidden -Wait; exit $LASTEXITCODE"
    )

    if dry_run:
        log('DRY-RUN', f"Would uninstall {name} using: {exe} {args}")
        return True, f"Dry-run: would uninstall {name} via '{exe} {args}'"

    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
            capture_output=True,
            text=True,
            timeout=180,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"Uninstall {name} → rc={result.returncode}")
        if not output:
            output = "Completed with no output."
        return success, output
    except subprocess.TimeoutExpired:
        return False, f"Uninstall timed out for {name}"
    except Exception as e:
        return False, f"Uninstall failed: {e}"


def execute_notify(payload, dry_run=False):
    """Send a modern WPF notification to the system."""
    try:
        data = json.loads(payload)
        msg_text = data.get('message', 'Notification from IT')
        # target_users is parsed but the modern UI currently shows on the active session
        # where the agent is running.
        target_users = data.get('target_users', ['All'])
    except Exception as e:
        return False, f"Failed to parse notification payload: {e}"

    if dry_run:
        log('DRY-RUN', f"Would send modern notification: '{msg_text}'")
        return True, f"Dry-run mode. Message: {msg_text}"

    return execute_modern_notify(msg_text)


def execute_modern_notify(message):
    """Launch a styled WPF notification window via PowerShell, with session handling."""
    if not powershell_available():
        log('WARN', "PowerShell unavailable; falling back to msg.exe notification.")
        try:
            subprocess.run(['msg', '*', message], capture_output=True, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE)
            return True, "PowerShell unavailable; used msg.exe fallback."
        except Exception as e:
            return False, f"Notification failed (no PowerShell): {e}"

    # Detect session
    session_id = 0
    try:
        current_session = ctypes.c_uint32()
        if WINDLL and WINDLL.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(current_session)):
            session_id = current_session.value
    except:
        pass

    if session_id == 0:
        # Service context cannot display UI; queue for the tray process running in a user session.
        enqueue_notification(message)
        return True, "Agent is running as a service; notification queued for user session."

    # Escape for use inside a C# string literal
    safe_msg = message.replace('\\', '\\\\').replace('"', '\\"')

    ps_content = f"""
$pfw = ([Reflection.Assembly]::LoadWithPartialName('PresentationFramework')).Location
$pfc = ([Reflection.Assembly]::LoadWithPartialName('PresentationCore')).Location
$wb  = ([Reflection.Assembly]::LoadWithPartialName('WindowsBase')).Location
$sx  = ([Reflection.Assembly]::LoadWithPartialName('System.Xaml')).Location

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

Add-Type -ReferencedAssemblies $pfw, $pfc, $wb, $sx, "System.Core", "mscorlib" @"
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;

public class ChimeraNotifyWin {{
    public static void Show(string msg) {{
        var win = new Window {{
            Title = "Chimera Control Message",
            Width = 460,
            Height = 260,
            WindowStyle = WindowStyle.None,
            AllowsTransparency = true,
            Background = Brushes.Transparent,
            WindowStartupLocation = WindowStartupLocation.CenterScreen,
            Topmost = true,
            ShowInTaskbar = true,
            ResizeMode = ResizeMode.NoResize
        }};

        var outerBorder = new Border {{
            Background = Brushes.White,
            BorderBrush = new SolidColorBrush(Color.FromRgb(0x1a, 0x25, 0x35)),
            BorderThickness = new Thickness(1.5),
            CornerRadius = new CornerRadius(12),
            Effect = new DropShadowEffect {{ BlurRadius = 15, Direction = 270, Opacity = 0.3, ShadowDepth = 3 }}
        }};

        var grid = new Grid();
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(50) }});
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(1, GridUnitType.Star) }});
        grid.RowDefinitions.Add(new RowDefinition {{ Height = new GridLength(70) }});

        // Header
        var headerBg = new Border {{
            Background = new SolidColorBrush(Color.FromRgb(0x1a, 0x25, 0x35)),
            CornerRadius = new CornerRadius(10, 10, 0, 0)
        }};
        var headerText = new TextBlock {{
            Text = "CHIMERA SECURITY NOTIFICATION",
            Foreground = new SolidColorBrush(Color.FromRgb(0xE0, 0xE0, 0xE0)),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            FontWeight = FontWeights.SemiBold,
            FontSize = 13
        }};
        headerBg.Child = headerText;
        Grid.SetRow(headerBg, 0);
        grid.Children.Add(headerBg);

        // Message
        var msgBlock = new TextBlock {{
            Text = msg,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 16,
            Foreground = new SolidColorBrush(Color.FromRgb(0x2D, 0x37, 0x48)),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            TextAlignment = TextAlignment.Center,
            Margin = new Thickness(30, 25, 30, 10)
        }};
        Grid.SetRow(msgBlock, 1);
        grid.Children.Add(msgBlock);

        // Button
        var btn = new Button {{
            Content = "Dismiss",
            Width = 120,
            Height = 36,
            Background = new SolidColorBrush(Color.FromRgb(0x3b, 0x82, 0xf6)),
            Foreground = Brushes.White,
            FontWeight = FontWeights.Bold,
            FontSize = 13,
            BorderThickness = new Thickness(0),
            Cursor = System.Windows.Input.Cursors.Hand,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        }};
        btn.Click += (s, e) => win.Close();
        Grid.SetRow(btn, 2);
        grid.Children.Add(btn);

        outerBorder.Child = grid;
        win.Content = outerBorder;
        win.ShowDialog();
    }}
}}
"@ -ErrorAction Stop

[ChimeraNotifyWin]::Show("{safe_msg}")
"""

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w', encoding='utf-8') as tf:
        tf.write(ps_content)
        temp_path = tf.name

    try:
        # Use -Sta to ensure WPF STA thread compatibility
        cmd = ['powershell', '-Sta', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', temp_path]

        def _run():
            res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                log('ERROR', f"Notification PowerShell failed (code {res.returncode})")
                log('DEBUG', f"PS Error: {res.stderr[:500]}")
            else:
                log('DEBUG', "Notification PowerShell completed successfully.")
            try: os.remove(temp_path)
            except: pass

        threading.Thread(target=_run, daemon=True).start()
        
        log('INFO', f"✓ Modern notification launched (Session {session_id}): {message[:50]}...")
        return True, f"Modern notification window launched in Session {session_id}."
    except Exception as e:
        log('WARN', f"Failed to launch modern notification: {e}")
        return False, str(e)


# ── Polling / Main ──────────────────────────────────────────────────────────


def _run_cmd(cmd, display_cmd=None):
    """Run a system command and return (success, output)."""
    show = display_cmd or ' '.join(cmd)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"{'✓' if success else '✗'} {show} → {output}")
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


# ── Interactive Shell Background Thread ─────────────────────────────────────
#
# Uses pywinpty to create a real Windows ConPTY so that:
#   - PowerShell runs in TRUE interactive mode
#   - `cd`, aliases, colors, and prompts all work correctly
#   - xterm.js receives proper ANSI escape sequences
#

async def interactive_shell_loop(server_url, device_id, shell_pref="cmd"):
    ws_url = server_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/agent/{device_id}"
    
    global HAS_PYWINPTY
    if not HAS_PYWINPTY:
        log('WARN', "pywinpty not found at startup; remote shell will use basic pipes.")

    while True:
        pty_proc = None
        is_pty = False
        try:
            system_root = os.environ.get('SystemRoot', 'C:\\Windows')
            ps_path = os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
            cmd_path = os.path.join(system_root, 'System32', 'cmd.exe')

            if shell_pref == "powershell" and powershell_available():
                shell_argv = [ps_path, "-NoLogo", "-NoProfile"]
            else:
                shell_argv = [cmd_path]

            connect_kwargs = {"origin": server_url}
            if ws_url.startswith("wss://") and _ssl_context:
                connect_kwargs["ssl"] = _ssl_context
            if AGENT_AUTH_TOKEN:
                connect_kwargs["extra_headers"] = {"Authorization": f"Bearer {AGENT_AUTH_TOKEN}"}

            async with websockets.connect(ws_url, **connect_kwargs) as ws:  # type: ignore
                loop = asyncio.get_event_loop()
                stop_event = threading.Event()
                clean_env = os.environ.copy()
                for k in ['PYTHONPATH', 'PYTHONHOME']:
                    clean_env.pop(k, None)

                # --- Spawn Method: WinPTY (Priority) ---
                if HAS_PYWINPTY:
                    try:
                        # WinPTY is much more reliable in Session 0 than ConPTY
                        pty_proc = PtyProcess.spawn(shell_argv, backend=Backend.WinPTY, cwd="C:\\", env=clean_env)
                        is_pty = True
                        log('INFO', f"Connected to Relay — Started WinPTY Shell (PID: {pty_proc.pid})")
                    except Exception as e:
                        log('WARN', f"WinPTY spawn failed: {e}. Falling back to Subprocess.")
                        HAS_PYWINPTY = False # Disable for this session

                # --- Spawn Method: Subprocess (Fallback) ---
                if pty_proc is None:
                    pty_proc = subprocess.Popen(
                        shell_argv,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env=clean_env,
                        cwd="C:\\",
                        bufsize=0, # Truly unbuffered
                        creationflags=CREATE_NO_WINDOW
                    )
                    is_pty = False
                    log('INFO', f"Connected to Relay — Started UNBUFFERED Subprocess Shell (PID: {pty_proc.pid})")

                output_queue: asyncio.Queue = asyncio.Queue()

                # --- Background thread: read process output → asyncio queue ---
                def _pty_reader():
                    nonlocal is_pty
                    log("DEBUG", f"Shell reader thread started for {'PTY' if is_pty else 'Subprocess'} PID {pty_proc.pid}")
                    while not stop_event.is_set():
                        try:
                            # Check if process is still alive
                            if is_pty:
                                if not pty_proc.isalive():
                                    break
                                data_str = pty_proc.read(4096)
                                if not data_str:
                                    break
                                data = data_str.encode('utf-8', errors='replace')
                            else:
                                if pty_proc.poll() is not None:
                                    break
                                # Raw OS read for pipes to avoid buffering
                                data = os.read(pty_proc.stdout.fileno(), 4096)
                                if not data:
                                    break
                            
                            char = data.decode('utf-8', errors='replace')
                            log("DEBUG", f"Shell reader received {len(data)} bytes")
                            asyncio.run_coroutine_threadsafe(output_queue.put(char), loop)
                        except Exception as e:
                            log("DEBUG", f"Shell reader exception: {repr(e)}")
                            break
                    asyncio.run_coroutine_threadsafe(output_queue.put(None), loop)
                    log("DEBUG", "Shell reader thread exiting.")

                reader_thread = threading.Thread(target=_pty_reader, daemon=True)
                reader_thread.start()

                # --- Coroutine: forward output → WebSocket ---
                async def _forward_output():
                    while True:
                        data = await output_queue.get()
                        if data is None:
                            break
                        try:
                            await ws.send(data)
                        except Exception as e:
                            log("DEBUG", f"WebSocket send failed: {repr(e)}")
                            break

                # --- Coroutine: forward WebSocket input → stdin ---
                RESIZE_PREFIX = '\x1bPTYR:'
                async def _forward_input():
                    nonlocal is_pty
                    try:
                        while True:
                            msg = await ws.recv()
                            # log("DEBUG", f"WS Input: {repr(msg)}")
                            if isinstance(msg, str) and msg.startswith(RESIZE_PREFIX):
                                if is_pty:
                                    # Parse ESC [ PTYR : rows ; cols
                                    try:
                                        parts = msg[len(RESIZE_PREFIX):].split(';')
                                        if len(parts) == 2:
                                            pty_proc.set_winsize(int(parts[0]), int(parts[1]))
                                    except: pass
                            else:
                                if isinstance(msg, str):
                                    msg = msg.encode('utf-8')
                                
                                if is_pty:
                                    # PtyProcess handles its own buffering
                                    pty_proc.write(msg.decode('utf-8', errors='replace'))
                                else:
                                    await loop.run_in_executor(None, pty_proc.stdin.write, msg)
                                    await loop.run_in_executor(None, pty_proc.stdin.flush)
                    except Exception:
                        pass
                    finally:
                        stop_event.set()

                await asyncio.gather(_forward_output(), _forward_input())
                log('INFO', "Interactive Shell Relay disconnected. Reconnecting...")

        except Exception as e:
            log('ERROR', f"Interactive Shell connection failed: {e}")
        finally:
            if pty_proc is not None:
                try:
                    if is_pty: pty_proc.terminate()
                    else: pty_proc.terminate()
                except Exception:
                    pass
        await asyncio.sleep(5)

def start_interactive_shell_thread(server_url, device_id, shell_pref="cmd"):
    def run():
        # new event loop for the thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(interactive_shell_loop(server_url, device_id, shell_pref))
    t = threading.Thread(target=run, daemon=True)
    t.start()


# ── Main Loop ───────────────────────────────────────────────────────────────

def main():
    log('INFO', f"Agent starting... (HAS_PYWINPTY={HAS_PYWINPTY})")
    parser = argparse.ArgumentParser(description='Admin Control System Agent')
    parser.add_argument('--server', default='https://localhost:8000',
                        help='Central server URL (default: https://localhost:8000)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print commands instead of executing them')
    parser.add_argument('--no-verify-ssl', action='store_true',
                        help='Disable SSL certificate verification (for self-signed certs)')
    parser.add_argument('--tray', action='store_true',
                        help='Show a system tray icon (requires pystray + Pillow)')
    parser.add_argument('--token', default=os.environ.get("AGENT_TOKEN") or os.environ.get("ACS_AGENT_TOKEN"),
                        help='Bearer token used for agent authentication')
    parser.add_argument('--service-name', default=SERVICE_NAME,
                        help='Windows Service name (NSSM) to guard/restart')
    parser.add_argument('--install-dir', help='Override install directory (default Program Files/YourAgent)')
    parser.add_argument('--uninstall', action='store_true',
                        help='Run protected uninstall flow (requires OTP) and exit')
    parser.add_argument('--otp', help='OTP for protected uninstall flow')
    parser.add_argument('--watchdog', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--parent-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--cert-sha256', help='Optional TLS certificate pin (SHA256 fingerprint)')
    parser.add_argument('--no-shell', action='store_true',
                        help='Disable remote interactive shell')
    parser.add_argument('--shell', choices=['powershell', 'cmd'], default='cmd',
                        help='Which shell to expose for remote interactive access (default: cmd)')
    parser.add_argument('--verify-otp', action='store_true',
                        help='Standalone OTP validation via GUI prompt (exits 0=success, 1=fail)')
    args = parser.parse_args()

    # If running uninstall without elevation, re-launch with UAC so service/cleanup succeeds.
    if args.uninstall and not is_admin():
        try:
            # ShellExecuteW passes params as a single string; avoid wrapping values
            # in inner double-quotes as they become literal characters in argv.
            extra_args = [f'--server={args.server}', '--uninstall']
            if args.no_verify_ssl:
                extra_args.append('--no-verify-ssl')
            if args.otp:
                extra_args.append(f'--otp={args.otp}')
            if args.service_name != SERVICE_NAME:
                extra_args.append(f'--service-name={args.service_name}')
            if args.install_dir:
                extra_args.append(f'--install-dir={args.install_dir}')
            if args.token:
                extra_args.append(f'--token={args.token}')
            params = " ".join(extra_args)
            log('INFO', f"Re-launching with elevation: {sys.executable} {params}")
            if WINDLL:
                WINDLL.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                return
        except Exception as e:
            log('WARN', f"Could not self-elevate for uninstall: {e}")
        # Continue without elevation (will likely fail), but we log above.

    # Configure SSL context globally
    global _ssl_context, AGENT_AUTH_TOKEN, PINNED_CERT_SHA256
    _ssl_context = ssl.create_default_context()
    if args.no_verify_ssl:
        _ssl_context.check_hostname = False
        _ssl_context.verify_mode = ssl.CERT_NONE
        log('WARN', 'SSL certificate verification is DISABLED (self-signed cert mode).')

    AGENT_AUTH_TOKEN = args.token
    pin_env = os.environ.get("PINNED_CERT_SHA256")
    PINNED_CERT_SHA256 = (args.cert_sha256 or pin_env or "").lower() or None

    install_root = resolve_install_root(args.install_dir)
    state = load_state()

    # Fallback to state if server is untouched from default (e.g., during uninstaller call)
    if args.server == 'https://localhost:8000' and state.get("server"):
        args.server = state.get("server")

    server = args.server.rstrip('/')

    # Watchdog mode (spawned by main agent)
    if args.watchdog:
        watchdog_loop(args.parent_pid or 0, args.service_name, server)
        return

    dry_run = args.dry_run
    try:
        ensure_dir(install_root)
    except Exception as e:
        log('WARN', f"Could not create install dir {install_root}: {e}. Falling back to runtime directory.")
        install_root = runtime_root()
        ensure_dir(install_root)
    staging_dir_path(install_root)

    if args.uninstall:
        success = protected_uninstall_flow(server, args.otp, args.service_name, install_root)
        sys.exit(0 if success else 1)

    if args.verify_otp:
        success = protected_uninstall_flow(server, None, args.service_name, install_root, verify_only=True)
        sys.exit(0 if success else 1)

    hostname = get_hostname()
    ip_address = get_ip()
    update_state(server=server, install_path=str(install_root), hostname=hostname)

    print()
    print('╔══════════════════════════════════════════════════╗')
    print('║       Admin Control System — Agent               ║')
    print('╠══════════════════════════════════════════════════╣')
    print(f'║  Server:    {server:<37}║')
    print(f'║  Hostname:  {hostname:<37}║')
    print(f'║  IP:        {ip_address:<37}║')
    print(f'║  Dry-run:   {"Yes" if dry_run else "No":<37}║')
    print('╚══════════════════════════════════════════════════╝')
    print(f"[*] Agent started. PID: {os.getpid()}")
    
    def ensure_tray_autostart(server_url):
        import winreg
        try:
            exe_path = sys.executable
            if 'python' in exe_path.lower():
                cmd = f'"{exe_path}" "{os.path.abspath(__file__)}" --tray --server={server_url} --no-verify-ssl'
            else:
                cmd = f'"{exe_path}" --tray --server={server_url} --no-verify-ssl'
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(key, "YourAgentTray", 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            log('INFO', '✓ Tray autostart registry key ensured in HKLM.')
        except Exception as e:
            log('WARN', f'Could not ensure tray autostart in HKLM: {e}')

    try:
        import ctypes
        session_id = ctypes.c_uint32()
        if WINDLL and WINDLL.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
             log('INFO', f"Agent Session ID: {session_id.value}")
             if session_id.value == 0 and not dry_run and not getattr(args, 'tray', False):
                 ensure_tray_autostart(server)
    except:
        pass
    log('INFO', f"Agent PID: {os.getpid()}")

    # ── Register device ─────────────────────────────────────────────────
    log('INFO', 'Collecting system information…')
    system_info = collect_system_info()
    log('INFO', 'Collecting all local users…')
    all_users = collect_all_users()
    
    log('INFO', 'Registering device with server…')
    state = load_state()
    device_id = state.get("device_id")
    if device_id:
        log('INFO', f"Cached device id {device_id}; refreshing registration.")

    while True:
        resp = api_call(server, 'POST', '/register', {
            'hostname': hostname,
            'ip_address': ip_address,
            'system_info': system_info,
            'all_users': all_users,
            'agent_version': AGENT_VERSION,
            'install_path': str(install_root),
        })
        if resp and 'device_id' in resp:
            device_id = resp['device_id']
            update_state(device_id=device_id, agent_version=AGENT_VERSION, last_seen=datetime.utcnow().isoformat() + "Z")
            log('INFO', f"Registered as device #{device_id}")
            break
        else:
            log('WARN', f"Registration failed, retrying in {POLL_INTERVAL}s…")
            time.sleep(POLL_INTERVAL)

    # ── Start platform protections ──────────────────────────────────────
    if not dry_run:
        start_watchdog_process(server, args.service_name)
        tg_thread = threading.Thread(target=tamper_guard_loop, args=(args.service_name,), daemon=True)
        tg_thread.start()

    # ── Start Interactive Shell Background Connection ───────────────────
    if not dry_run and not args.no_shell:
        start_interactive_shell_thread(server, device_id, args.shell)
    else:
        log('INFO', "Interactive shell disabled (dry-run or --no-shell).")

    # ── Start Event Log Collector Background Thread ───────────────────
    if not dry_run:
        evt_thread = threading.Thread(
            target=event_log_collector_thread,
            args=(server, device_id, hostname),
            daemon=True
        )
        evt_thread.start()
    else:
        log('DRY-RUN', "Skipping event log collection in dry-run mode.")

    # ── Start System Info Refresh Background Thread ───────────────────
    SYS_INFO_INTERVAL = 60  # refresh system info every 60 seconds to reduce overhead

    def sys_info_refresh_loop():
        while True:
            time.sleep(SYS_INFO_INTERVAL)
            # Fetching silently in background
            fresh_info = collect_system_info()
            fresh_users = collect_all_users()
            api_call(server, 'POST', '/register', {
                'hostname': hostname,
                'ip_address': get_ip(),
                'system_info': fresh_info,
                'all_users': fresh_users,
                'agent_version': AGENT_VERSION,
                'install_path': str(install_root),
            })

    if not dry_run:
        si_thread = threading.Thread(target=sys_info_refresh_loop, daemon=True)
        si_thread.start()

    # ── Start Software Inventory Background Thread ────────────────────────
    if not dry_run:
        sw_thread = threading.Thread(
            target=software_inventory_thread,
            args=(server, device_id),
            daemon=True
        )
        sw_thread.start()
    else:
        log('DRY-RUN', "Skipping software inventory sync in dry-run mode.")

    # ── Start Activity Tracking Background Thread ─────────────────────────
    if not dry_run and session_id.value != 0:
        act_thread = threading.Thread(
            target=activity_sampler_thread,
            args=(server, device_id),
            daemon=True
        )
        act_thread.start()
    elif not dry_run:
        log('DEBUG', "Skipping activity tracking in non-interactive session.")
    else:
        log('DRY-RUN', "Skipping activity tracking in dry-run mode.")

    # ── Start Patch Management Thread ───────────────────────────────────
    if not dry_run and session_id.value == 0:
        upd_thread = threading.Thread(
            target=update_poll_loop,
            args=(server, device_id, args.service_name, install_root),
            daemon=True
        )
        upd_thread.start()
    elif not dry_run:
        log('DEBUG', f"Patch management disabled in user session (Session ID {session_id.value}).")

    # ── Polling loop ────────────────────────────────────────────────────
    log('INFO', f"Agent Elevation: {'Administrator' if is_admin() else 'Standard User'}")
    log('INFO', f"Polling for commands every {POLL_INTERVAL}s…")

    # If --tray mode: run poll loop in background thread and hand off to system tray
    if getattr(args, 'tray', False):
        poll_thread = threading.Thread(target=lambda: main_loop(server, device_id, dry_run), daemon=True)
        poll_thread.start()
        run_with_tray(server, device_id)
        return

    main_loop(server, device_id, dry_run)


def main_loop(server, device_id, dry_run=False):
    """The main polling loop — runs indefinitely."""
    global LAST_SYNC_TS
    last_state_write = time.time()
    while True:
        try:
            LAST_SYNC_TS = datetime.utcnow()
            resp = api_call(server, 'GET', f'/get_command/{device_id}')
            if resp and resp.get('command'):
                cmd = resp['command']
                cmd_id = cmd['id']
                action = cmd['action']
                username = cmd.get('username', '')

                payload = cmd.get('payload', '')

                log('INFO', f"⬇ Command #{cmd_id}: {action} {username if username else ''}")

                # Execute
                if action == 'grant':
                    success, output = execute_grant(username, dry_run)
                    # After grant/revoke/create_user, update admin list instantly
                    _, _, admin_list = execute_check(dry_run)
                    report_result(server, cmd_id, success, output, admin_list)

                elif action == 'revoke':
                    success, output = execute_revoke(username, dry_run)
                    _, _, admin_list = execute_check(dry_run)
                    report_result(server, cmd_id, success, output, admin_list)

                elif action == 'check':
                    success, output, admin_list = execute_check(dry_run)
                    report_result(server, cmd_id, success, output, admin_list)

                elif action == 'shell':
                    success, output = execute_shell(payload, dry_run)
                    report_result(server, cmd_id, success, output)

                elif action == 'create_user':
                    success, output = execute_create_user(username, payload, dry_run)
                    _, _, admin_list = execute_check(dry_run)
                    report_result(server, cmd_id, success, output, admin_list)

                elif action == 'notify':
                    success, output = execute_notify(payload, dry_run)
                    report_result(server, cmd_id, success, output)

                elif action == 'get_bitlocker_key':
                    success, output = execute_get_bitlocker_key(payload, dry_run)
                    report_result(server, cmd_id, success, output)

                elif action == 'uninstall_software':
                    success, output = execute_uninstall(payload, dry_run)
                    report_result(server, cmd_id, success, output)

                else:
                    log('WARN', f"Unknown action: {action}")
                    report_result(server, cmd_id, False, f"Unknown action: {action}")

        except KeyboardInterrupt:
            log('INFO', 'Agent shutting down.')
            sys.exit(0)
        except Exception as e:
            log('ERROR', f"Unexpected error: {e}")

        if time.time() - last_state_write >= 60:
            try:
                update_state(last_seen=LAST_SYNC_TS.isoformat() + "Z")
            except Exception:
                pass
            last_state_write = time.time()

        time.sleep(POLL_INTERVAL)


def report_result(server, cmd_id, success, output, admin_list=None):
    """Post command result back to the server."""
    body = {
        'command_id': cmd_id,
        'status': 'completed' if success else 'failed',
        'result': output,
    }
    if admin_list is not None:
        body['admin_list'] = admin_list

    resp = api_call(server, 'POST', '/command_result', body)
    if resp:
        log('INFO', f"⬆ Result for #{cmd_id} reported: {'completed' if success else 'failed'}")
    else:
        log('WARN', f"Failed to report result for #{cmd_id}")


# ── System Tray Icon ─────────────────────────────────────────────────────────

def _create_tray_image():
    """Generate a simple shield icon programmatically using Pillow."""
    from PIL import Image, ImageDraw  # type: ignore
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Dark navy shield background
    draw.polygon([(32, 4), (58, 16), (58, 36), (32, 60), (6, 36), (6, 16)], fill=(26, 37, 53))
    # White 'A' letter for "Admin"
    draw.text((22, 18), "A", fill=(255, 255, 255))
    return img


def run_with_tray(server, device_id):
    """Launch agent main loop as a background thread, then show a system tray icon."""
    try:
        import pystray  # type: ignore
    except ImportError:
        log('WARN', "pystray not installed — running without tray. Install with: pip install pystray Pillow")
        main_loop(server, device_id)
        return

    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_debug.log')

    def read_log_tail(lines=200):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                return ''.join(f.readlines()[-lines:])
        except Exception:
            return "No log entries yet."

    def open_console(icon=None, item=None):
        """Lightweight status console window."""
        def _show():
            import tkinter as tk
            from tkinter import scrolledtext

            state = load_state()
            win = tk.Tk()
            win.title("YourAgent Console")
            win.geometry("520x360")
            win.resizable(False, False)

            status_color = "#2ecc71"
            status_text = "Online"
            if not LAST_SYNC_TS or (datetime.utcnow() - LAST_SYNC_TS).total_seconds() > 45:
                status_color = "#f1c40f"
                status_text = "Idle"

            header = tk.Frame(win, bg="#1a2535", height=50)
            header.pack(fill="x")
            tk.Label(header, text="YourAgent Endpoint", fg="white", bg="#1a2535",
                     font=("Segoe UI", 12, "bold")).pack(side="left", padx=14, pady=10)
            tk.Label(header, text=f"{status_text}", fg=status_color, bg="#1a2535",
                     font=("Segoe UI", 11, "bold")).pack(side="right", padx=14)

            body = tk.Frame(win, padx=12, pady=10)
            body.pack(fill="both", expand=True)

            tk.Label(body, text=f"Server: {server}", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Device ID: {device_id}", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Agent version: {AGENT_VERSION}", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Last sync: {LAST_SYNC_TS.isoformat() if LAST_SYNC_TS else '—'}", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Install path: {state.get('install_path', 'unknown')}", anchor="w").pack(fill="x")

            tk.Label(body, text="Recent log:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
            log_box = scrolledtext.ScrolledText(body, height=10, font=("Consolas", 9))
            log_box.pack(fill="both", expand=True)
            log_box.insert("end", read_log_tail(120))
            log_box.configure(state="disabled")

            def refresh():
                log_box.configure(state="normal")
                log_box.delete("1.0", "end")
                log_box.insert("end", read_log_tail(120))
                log_box.configure(state="disabled")
                win.update_idletasks()

            tk.Button(body, text="Refresh", command=refresh).pack(anchor="e", pady=6)
            win.mainloop()

        threading.Thread(target=_show, daemon=True).start()

    def on_open_log(icon, item):
        if hasattr(os, "startfile"):
            os.startfile(log_path)  # type: ignore[attr-defined]

    def flush_queued_notifications():
        """Display notifications queued by the service (session 0) instance."""
        while True:
            try:
                msg = dequeue_notification()
                if msg:
                    # Force re-check PowerShell availability before displaying
                    global _POWERSHELL_LAST_CHECK
                    _POWERSHELL_LAST_CHECK = 0.0
                    execute_modern_notify(msg)
                    continue
            except Exception as e:
                log('WARN', f"Tray notify watcher error: {e}")
            time.sleep(5)

    icon_image = _create_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem("🖥️ Open Console", open_console, default=True),
        pystray.MenuItem("📄 Open Log", on_open_log),
    )
    tray = pystray.Icon("ACS Agent", icon_image, "ACS Agent", menu)
    log('INFO', "🖥️  System tray icon active. Right-click the tray for status and logs.")
    threading.Thread(target=flush_queued_notifications, daemon=True).start()
    tray.run()


if __name__ == '__main__':
    main()
