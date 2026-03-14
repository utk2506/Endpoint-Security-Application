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

def is_admin():
    """Check if the agent is running with Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore
    except:
        return False
import subprocess
import sys
import time
import threading
import asyncio
import websockets  # type: ignore
from datetime import datetime
from urllib import request, error, parse

# ── Configuration ───────────────────────────────────────────────────────────

POLL_INTERVAL = 5  # seconds
LOG_COLLECT_INTERVAL = 60  # seconds — how often to collect event logs

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

# ── Helpers ─────────────────────────────────────────────────────────────────

def log(level, message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}]  {message}"
    print(line, flush=True)
    try:
        # Write to a file so we can view logs from elevated windows
        # Use absolute path to avoid writing to System32 when elevated
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_debug.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass


def api_call(base_url, method, path, body=None):
    """Simple HTTP helper using only urllib (no external deps)."""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode('utf-8') if body else None
    req = request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')

    try:
        with request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode('utf-8'))
    except error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        log('ERROR', f"API {method} {path} → {e.code}: {detail}")
        return None
    except error.URLError as e:
        log('ERROR', f"Cannot reach server: {e.reason}")
        return None


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

# Disks
$disksRaw = Get-WmiObject Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    @{
        drive    = $_.DeviceID
        size_gb  = [math]::Round($_.Size / 1GB, 2)
        free_gb  = [math]::Round($_.FreeSpace / 1GB, 2)
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
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            log('INFO', f"✓ System info collected (CPU: {data.get('cpu_name','?')}, RAM: {data.get('ram_total_gb','?')} GB)")
            return data
        else:
            log('WARN', f"System info PowerShell failed: {result.stderr.strip()[:200]}")  # type: ignore
    except subprocess.TimeoutExpired:
        log('WARN', "System info collection timed out")
    except Exception as e:
        log('WARN', f"System info error: {e}")
    return None

# ── Commands ────────────────────────────────────────────────────────────────

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
            cmd, capture_output=True, text=True, timeout=15
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0

        members = []
        if success:
            in_members = False
            for line in result.stdout.strip().splitlines():
                line = line.strip()
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

    cmd = ['powershell', '-NoProfile', '-NonInteractive', '-Command', payload]
    try:
        result = subprocess.run(  # type: ignore
            cmd, capture_output=True, text=True, timeout=60
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        success = result.returncode == 0
        log('INFO' if success else 'WARN', f"Shell execution {'✓' if success else '✗'} → length: {len(output)}")
        return success, output
    except subprocess.TimeoutExpired:
        log('WARN', "Shell execution timed out")
        return False, "Command timed out after 60 seconds"
    except Exception as e:
        log('ERROR', f"Shell execution failed: {e}")
        return False, str(e)


def _run_cmd(cmd, display_cmd=None):
    """Run a system command and return (success, output)."""
    show = display_cmd or ' '.join(cmd)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
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

async def interactive_shell_loop(server_url, device_id):
    ws_url = server_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws/agent/{device_id}"
    while True:
        pty_proc = None
        try:
            async with websockets.connect(ws_url, origin=server_url) as ws:  # type: ignore
                log('INFO', "Connected to Interactive Shell Relay — starting PTY")

                from winpty import PtyProcess  # type: ignore
                loop = asyncio.get_event_loop()
                stop_event = threading.Event()

                # Spawn PowerShell inside a real ConPTY — start with generous size;
                # the portal will send a resize signal once xterm.js is laid out.
                pty_proc = PtyProcess.spawn(
                    'powershell.exe -NoLogo -NoProfile',
                    dimensions=(50, 220),
                    cwd=os.path.expanduser('~')
                )

                # Send a space and a backspace to force the prompt to render
                # immediately without triggering a newline/command execution
                pty_proc.write(' \x08')

                output_queue: asyncio.Queue = asyncio.Queue()

                # --- Background thread: read PTY output → asyncio queue ---
                def _pty_reader():
                    while not stop_event.is_set():
                        try:
                            if not pty_proc.isalive():  # type: ignore[attr-defined]
                                break
                            data = pty_proc.read(4096)  # type: ignore[attr-defined]
                            if data:
                                asyncio.run_coroutine_threadsafe(
                                    output_queue.put(data), loop
                                )
                        except Exception:
                            break
                    asyncio.run_coroutine_threadsafe(output_queue.put(None), loop)

                reader_thread = threading.Thread(target=_pty_reader, daemon=True)
                reader_thread.start()

                # --- Coroutine: forward PTY output → WebSocket ---
                async def _forward_output():
                    while True:
                        data = await output_queue.get()
                        if data is None:
                            break
                        try:
                            await ws.send(data)
                        except Exception:
                            break

                # --- Coroutine: forward WebSocket input → PTY stdin ---
                # Special signal: ESC P T Y R : rows : cols  → resize the PTY
                RESIZE_PREFIX = '\x1bPTYR:'

                async def _forward_input():
                    try:
                        while True:
                            msg = await ws.recv()
                            if isinstance(msg, str) and msg.startswith(RESIZE_PREFIX):
                                # Parse \x1bPTYR:{rows}:{cols} and resize PTY
                                try:
                                    parts = str(msg).replace(RESIZE_PREFIX, '', 1).split(':')
                                    rows, cols = int(parts[0]), int(parts[1])
                                    rows = max(1, min(rows, 200))
                                    cols = max(10, min(cols, 500))
                                    await loop.run_in_executor(
                                        None, pty_proc.setwinsize, rows, cols  # type: ignore[attr-defined]
                                    )
                                    log('INFO', f"PTY resized to {rows}×{cols}")
                                except Exception:
                                    pass
                            else:
                                await loop.run_in_executor(None, pty_proc.write, msg)  # type: ignore[attr-defined]
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
                    pty_proc.terminate()
                except Exception:
                    pass
        await asyncio.sleep(5)

def start_interactive_shell_thread(server_url, device_id):
    def run():
        # new event loop for the thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(interactive_shell_loop(server_url, device_id))
    t = threading.Thread(target=run, daemon=True)
    t.start()


# ── Main Loop ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Admin Control System Agent')
    parser.add_argument('--server', default='http://localhost:8000',
                        help='Central server URL (default: http://localhost:8000)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print commands instead of executing them')
    args = parser.parse_args()

    server = args.server.rstrip('/')
    dry_run = args.dry_run
    hostname = get_hostname()
    ip_address = get_ip()

    print()
    print('╔══════════════════════════════════════════════════╗')
    print('║       Admin Control System — Agent               ║')
    print('╠══════════════════════════════════════════════════╣')
    print(f'║  Server:    {server:<37}║')
    print(f'║  Hostname:  {hostname:<37}║')
    print(f'║  IP:        {ip_address:<37}║')
    print(f'║  Dry-run:   {"Yes" if dry_run else "No":<37}║')
    print('╚══════════════════════════════════════════════════╝')
    print()

    # ── Register device ─────────────────────────────────────────────────
    log('INFO', 'Collecting system information…')
    system_info = collect_system_info()
    
    log('INFO', 'Registering device with server…')
    device_id = None

    while device_id is None:
        resp = api_call(server, 'POST', '/register', {
            'hostname': hostname,
            'ip_address': ip_address,
            'system_info': system_info,
        })
        if resp and 'device_id' in resp:
            device_id = resp['device_id']
            log('INFO', f"Registered as device #{device_id}")
        else:
            log('WARN', f"Registration failed, retrying in {POLL_INTERVAL}s…")
            time.sleep(POLL_INTERVAL)

    # ── Start Interactive Shell Background Connection ───────────────────
    if not dry_run:
        start_interactive_shell_thread(server, device_id)
    else:
        log('DRY-RUN', "Skipping interactive shell connection in dry-run mode.")

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
    SYS_INFO_INTERVAL = 10  # refresh system info every 10 seconds for real-time monitoring

    def sys_info_refresh_loop():
        while True:
            time.sleep(SYS_INFO_INTERVAL)
            # Fetching silently in background
            fresh_info = collect_system_info()
            api_call(server, 'POST', '/register', {
                'hostname': hostname,
                'ip_address': get_ip(),
                'system_info': fresh_info,
            })

    if not dry_run:
        si_thread = threading.Thread(target=sys_info_refresh_loop, daemon=True)
        si_thread.start()

    # ── Polling loop ────────────────────────────────────────────────────
    log('INFO', f"Agent Elevation: {'Administrator' if is_admin() else 'Standard User'}")
    log('INFO', f"Polling for commands every {POLL_INTERVAL}s…")

    while True:
        try:
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
                    report_result(server, cmd_id, success, output)

                elif action == 'revoke':
                    success, output = execute_revoke(username, dry_run)
                    report_result(server, cmd_id, success, output)

                elif action == 'check':
                    success, output, admin_list = execute_check(dry_run)
                    report_result(server, cmd_id, success, output, admin_list)

                elif action == 'shell':
                    success, output = execute_shell(payload, dry_run)
                    report_result(server, cmd_id, success, output)

                else:
                    log('WARN', f"Unknown action: {action}")
                    report_result(server, cmd_id, False, f"Unknown action: {action}")

        except KeyboardInterrupt:
            log('INFO', 'Agent shutting down.')
            sys.exit(0)
        except Exception as e:
            log('ERROR', f"Unexpected error: {e}")

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


if __name__ == '__main__':
    main()
