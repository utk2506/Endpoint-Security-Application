"""
Admin Control System — Agent (entry point)
==========================================
This file is intentionally kept slim. All functionality lives in the modules listed below.

Run with administrator privileges:
    python agent.py --server https://SERVER_IP:8000

Optional: --dry-run   (prints commands instead of executing them)
"""

import argparse
import ctypes
import json
import os
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Single-instance mutex helpers (Windows) ────────────────────────────────
_MUTEX_HANDLE = None  # keep reference so it is not GC'd

def _acquire_mutex(name: str) -> bool:
    """Try to create a named Windows mutex. Returns True if this process is first."""
    global _MUTEX_HANDLE
    try:
        _lib = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = _lib.CreateMutexW(None, True, name)
        if handle and _lib.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _lib.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True  # non-Windows fallback — allow startup

# ── Stdout/stderr redirect for --tray EXE diagnostics ─────────────────────
try:
    if "--tray" in "".join(sys.argv):
        sys.stdout = open(r"C:\Users\ITSupport\AppData\Local\Temp\agent_stdout.log", 'a', encoding='utf-8')
        sys.stderr = open(r"C:\Users\ITSupport\AppData\Local\Temp\agent_stderr.log", 'a', encoding='utf-8')
        print(f"--- NEW RUN WITH TRAY ARGS: {sys.argv} ---", flush=True)
except Exception:
    pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# ── Module imports ──────────────────────────────────────────────────────────
from config import (
    AGENT_VERSION, SERVICE_NAME, SWAP_LOCK_FILE,
    POLL_INTERVAL, WINDLL, CREATE_NO_WINDOW,
    TRAY_FLAG_FILE, TRAY_SUPERVISOR_INTERVAL, TRAY_SUPERVISOR_LOG,
)
from logger import log
from state import (
    load_state, save_state, update_state,
    runtime_root, ensure_dir,
)
from network import api_call
from system_info import get_hostname, get_ip, collect_system_info, collect_all_users
from event_logs import event_log_collector_thread
from software import software_inventory_thread
from commands import (
    execute_grant, execute_revoke, execute_check,
    execute_shell, execute_create_user, execute_notify,
    execute_uninstall,
)
from system_info import execute_get_bitlocker_key
from shell_relay import start_interactive_shell_thread
from updater import (
    update_poll_loop, resolve_install_root, staging_dir_path,
)
from watchdog import (
    start_watchdog_process, watchdog_loop, tamper_guard_loop,
)
from uninstaller import protected_uninstall_flow
from tray import run_with_tray

# ── Runtime state ─────────────────────────────────────────────────────────
device_id = None
LAST_SYNC_TS: "datetime | None" = None
args = None


# ── Windows setup ─────────────────────────────────────────────────────────

if sys.platform == "win32" and WINDLL:
    try:
        hwnd = WINDLL.kernel32.GetConsoleWindow()
        if hwnd:
            WINDLL.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        SEM_NOOPENFILEERRORBOX = 0x8000
        WINDLL.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return bool(WINDLL and WINDLL.shell32.IsUserAnAdmin() != 0)
    except Exception:
        return False


# ── Tray helpers ─────────────────────────────────────────────────────────────

def tray_flag_path(install_root: Path) -> Path:
    path = Path(TRAY_FLAG_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def tray_supervisor_log_path() -> Path:
    path = Path(TRAY_SUPERVISOR_LOG)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def supervisor_log(event: str, **fields) -> None:
    ts = datetime.utcnow().isoformat() + "Z"
    parts = [f"event={event}"] + [f"{k}={fields[k]}" for k in sorted(fields)]
    line = f"{ts}\t" + "\t".join(parts)
    try:
        log_path = tray_supervisor_log_path()
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        log("INFO", f"[tray-supervisor] {line}")
    except Exception:
        pass


def build_tray_command(server_url: str) -> str:
    exe_path = sys.executable
    if 'python' in exe_path.lower():
        target = f'"{exe_path}" "{os.path.abspath(__file__)}"'
    else:
        target = f'"{exe_path}"'
    arg_list = f"'--tray --server={server_url} --no-verify-ssl'"
    ps = (
        "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass "
        f"-Command \"Start-Process {target} -ArgumentList {arg_list} -WindowStyle Hidden\""
    )
    return ps


def tray_present_in_user_session() -> tuple[bool, list]:
    """Return (is_running, process_list) for agent.exe --tray processes.
    
    Uses the named mutex to check if a tray instance is alive — this is
    reliable regardless of which session the process is in.
    """
    processes = []
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process -Name agent -IncludeUserName -ErrorAction SilentlyContinue | "
             "Select-Object Id,SessionId,UserName | ConvertTo-Json -Depth 2"],
            creationflags=CREATE_NO_WINDOW,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if out.strip():
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for entry in data or []:
                processes.append({
                    "pid": int(entry.get("Id", -1)) if entry.get("Id") is not None else None,
                    "session": int(entry.get("SessionId", -1)) if entry.get("SessionId") is not None else None,
                    "user": entry.get("UserName"),
                    "source": "powershell",
                })
    except Exception:
        pass

    # Check the named mutex — if it exists another tray instance is alive
    # (works regardless of which Windows session the process is in)
    tray_mutex_alive = False
    try:
        _lib = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = _lib.OpenMutexW(0x00100000, False, "Global\\SentraGuard_Tray")  # SYNCHRONIZE
        if h:
            tray_mutex_alive = True
            _lib.CloseHandle(h)
    except Exception:
        pass

    # Fall back to session-based detection if mutex check is inconclusive
    if not tray_mutex_alive:
        running_in_session = any((p.get("session") not in (None, -1)) for p in processes)
        return running_in_session, processes

    return tray_mutex_alive, processes


def active_console_session_id() -> int:
    try:
        if WINDLL:
            sid = int(WINDLL.kernel32.WTSGetActiveConsoleSessionId())
            return 0 if sid == 0xFFFFFFFF else sid
    except Exception:
        pass
    return 0


def active_session_info() -> tuple[int, "str | None"]:
    """Return (session_id, username) preferring quser for username context."""
    sid = 0
    user = None
    try:
        out = subprocess.check_output(
            ["quser"],
            text=True,
            creationflags=CREATE_NO_WINDOW,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if not line.strip() or line.lower().startswith("username"):
                continue
            parts = line.replace(">", " ").split()
            if len(parts) >= 4 and parts[3].lower().startswith("active"):
                user = parts[0]
                try:
                    sid = int(parts[2])
                except Exception:
                    sid = 0
                break
    except Exception:
        pass

    if sid == 0:
        sid = active_console_session_id()
    return sid, user


def launch_tray_into_active_session(server_url: str, install_root: Path) -> tuple[bool, int, str, str]:
    """Use WTS token duplication to launch tray into the active console session.
    Returns (success, returncode, stdout, stderr)."""
    exe_path = install_root / "agent.exe"
    if not exe_path.exists():
        exe_path = Path(sys.executable)

    ps_script = (
        "Add-Type -TypeDefinition '"
        "using System;using System.Runtime.InteropServices;"
        "public class SgWts2{"
        "[DllImport(\"kernel32.dll\")] public static extern uint WTSGetActiveConsoleSessionId();"
        "[DllImport(\"wtsapi32.dll\")] public static extern bool WTSQueryUserToken(uint s,out IntPtr t);"
        "[DllImport(\"advapi32.dll\",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool DuplicateTokenEx(IntPtr h,uint a,IntPtr p,int i,int t,out IntPtr n);"
        "[DllImport(\"advapi32.dll\",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool CreateProcessAsUser(IntPtr t,string app,string cmd,IntPtr pa,IntPtr ta,bool inh,uint cf,IntPtr env,string dir,ref SI si,out PI pi);"
        "[DllImport(\"kernel32.dll\")] public static extern bool CloseHandle(IntPtr h);"
        "[StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] public struct SI{public int cb;public string res,desk,title;public uint x,y,xs,ys,xc,yc,fa,fl;public short sw,_2;public IntPtr _3,si,so,se;}"
        "[StructLayout(LayoutKind.Sequential)] public struct PI{public IntPtr hp,ht;public uint pid,tid;}"
        "}' -ErrorAction Stop;"
        "$sid=[SgWts2]::WTSGetActiveConsoleSessionId();"
        "if($sid -eq 0xffffffff -or $sid -eq 0){{exit 1}};"
        "$tok=[IntPtr]::Zero;"
        "if([SgWts2]::WTSQueryUserToken($sid,[ref]$tok)){"
        "$dup=[IntPtr]::Zero;"
        "[SgWts2]::DuplicateTokenEx($tok,0x10000000,[IntPtr]::Zero,2,1,[ref]$dup)|Out-Null;"
        "$si=New-Object SgWts2+SI;$si.cb=[System.Runtime.InteropServices.Marshal]::SizeOf($si);$si.desk='winsta0\\default';"
        "$pi=New-Object SgWts2+PI;"
        f"[SgWts2]::CreateProcessAsUser($dup,$null,'\"{exe_path}\" --tray --server={server_url} --no-verify-ssl',[IntPtr]::Zero,[IntPtr]::Zero,$false,0x08000000,[IntPtr]::Zero,$null,[ref]$si,[ref]$pi)|Out-Null;"
        "[SgWts2]::CloseHandle($dup)|Out-Null;[SgWts2]::CloseHandle($tok)|Out-Null; exit 0"
        "} else { exit 1 }"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            timeout=20, text=True, errors="ignore",
        )
        return proc.returncode == 0, proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return False, -1, "", str(e)


def ensure_tray_scheduled_task(server_url: str, install_root: Path, username: "str | None") -> tuple[bool, int, str, str]:
    """Register + start an interactive scheduled task for the active user."""
    if not username:
        return False, -1, "", "no active user"

    exe_path = install_root / "agent.exe"
    if not exe_path.exists():
        exe_path = Path(sys.executable)

    _user = username.replace("'", "''")
    ps_script = (
        "$arg='--tray --server=" + server_url + " --no-verify-ssl';"
        "$action=New-ScheduledTaskAction -Execute 'powershell.exe' "
        "-Argument ('-WindowStyle Hidden -ExecutionPolicy Bypass -Command \"Start-Process '\"'\"'" + str(exe_path) +
        "'\"'\"' -ArgumentList '\"'\"''\"'\"'+$arg+'\"'\"''\"'\"' -WindowStyle Hidden\"');"
        "$t1=New-ScheduledTaskTrigger -AtLogOn -User '" + _user + "';"
        "$t2=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30) -RepetitionInterval (New-TimeSpan -Minutes 2);"
        "$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) "
        "-DisallowStartIfOnBatteries $false -StopIfGoingOnBatteries $false;"
        "$principal=New-ScheduledTaskPrincipal -UserId '" + _user + "' -LogonType Interactive -RunLevel Limited;"
        "Register-ScheduledTask -TaskName 'SentraGuardTray' -Action $action -Trigger @($t1,$t2) "
        "-Settings $settings -Principal $principal -Force | Out-Null;"
        "Start-ScheduledTask -TaskName 'SentraGuardTray';"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW,
            timeout=20,
        )
        return proc.returncode == 0, proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return False, -1, "", str(e)


def tray_supervisor_loop(server_url: str, install_root: Path) -> None:
    """Service-side self-heal: keep a tray running in the active user session."""
    flag = tray_flag_path(install_root)
    failure_streak = 0
    supervisor_log("start", interval=TRAY_SUPERVISOR_INTERVAL, flag_path=str(flag))
    try:
        time.sleep(10)  # first quick check after startup
    except Exception:
        pass
    while True:
        try:
            sid, user = active_session_info()
            tray_running, processes = tray_present_in_user_session()
            force_launch = flag.exists()
            pids = ",".join(str(p.get("pid")) for p in processes if p.get("pid"))
            supervisor_log("tick", session_id=sid, user=user or "", flag=force_launch,
                           tray_running=tray_running, pids=pids)

            if sid > 0 and (force_launch or not tray_running):
                log('INFO', f"Tray supervisor launching tray (force={force_launch}, session={sid}, running={tray_running})")
                success, rc, out, err = launch_tray_into_active_session(server_url, install_root)
                supervisor_log("launch", session_id=sid, user=user or "", force=force_launch,
                               rc=rc, stdout=(out or "")[:200], stderr=(err or "")[:200])
                if success:
                    failure_streak = 0
                    log('INFO', "Tray supervisor launch succeeded.")
                    if flag.exists():
                        flag.unlink(missing_ok=True)
                else:
                    time.sleep(5)
                    success2, rc2, out2, err2 = launch_tray_into_active_session(server_url, install_root)
                    supervisor_log("retry", session_id=sid, user=user or "", rc=rc2,
                                   stdout=(out2 or "")[:200], stderr=(err2 or "")[:200])
                    if success2:
                        failure_streak = 0
                        log('INFO', "Tray supervisor retry succeeded.")
                        if flag.exists():
                            flag.unlink(missing_ok=True)
                    else:
                        failure_streak += 1
                        log('WARN', "Tray supervisor retry failed.")
            else:
                failure_streak = 0 if tray_running else failure_streak

            if failure_streak >= 2 and sid > 0 and not tray_running:
                ok, rc_t, out_t, err_t = ensure_tray_scheduled_task(server_url, install_root, user)
                supervisor_log("task-register", session_id=sid, user=user or "", rc=rc_t,
                               stdout=(out_t or "")[:200], stderr=(err_t or "")[:200], success=ok)
                failure_streak = 0

            if tray_running and flag.exists():
                flag.unlink(missing_ok=True)

            if force_launch and sid == 0:
                log('INFO', "Tray relaunch flag set but no active console session; will retry.")
        except Exception as e:
            log('WARN', f"Tray supervisor loop error: {e}")
            supervisor_log("error", error=str(e))

        time.sleep(TRAY_SUPERVISOR_INTERVAL)


# ── Result reporting ──────────────────────────────────────────────────────

def report_result(server: str, cmd_id, success: bool, output: str, admin_list=None) -> None:
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


# ── Main polling loop ─────────────────────────────────────────────────────

def main_loop(server: str, initial_device_id, dry_run: bool = False) -> None:
    """Polls for commands indefinitely."""
    global LAST_SYNC_TS
    from state import load_state
    while True:
        try:
            device_id = load_state().get("device_id") or initial_device_id
            LAST_SYNC_TS = datetime.utcnow()
            resp = api_call(server, 'GET', f'/get_command/{device_id}')
            if resp and resp.get('command'):
                cmd = resp['command']
                cmd_id = cmd['id']
                action = cmd['action']
                username = cmd.get('username', '')
                payload = cmd.get('payload', '')

                log('INFO', f"⬇ Command #{cmd_id}: {action} {username if username else ''}")

                if action == 'grant':
                    success, output = execute_grant(username, dry_run)
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

        try:
            if LAST_SYNC_TS:
                update_state(last_seen=LAST_SYNC_TS.isoformat() + "Z")
        except Exception:
            pass

        time.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    import network as _net

    log('INFO', f"Agent starting... (v{AGENT_VERSION})")
    parser = argparse.ArgumentParser(description='Admin Control System Agent')
    parser.add_argument('--server', default='https://localhost:8000')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-verify-ssl', action='store_true')
    parser.add_argument('--tray', action='store_true')
    parser.add_argument('--token', default=os.environ.get("AGENT_TOKEN") or os.environ.get("ACS_AGENT_TOKEN"))
    parser.add_argument('--service-name', default=SERVICE_NAME)
    parser.add_argument('--install-dir')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--otp')
    parser.add_argument('--watchdog', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--parent-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--cert-sha256')
    parser.add_argument('--no-shell', action='store_true')
    parser.add_argument('--shell', choices=['powershell', 'cmd'], default='cmd')
    parser.add_argument('--verify-otp', action='store_true')
    parser.add_argument('--force-update-check', action='store_true')
    parser.add_argument('--tray-open', action='store_true')

    global args
    args = parser.parse_args()

    # ── Single-instance guard ────────────────────────────────────────────────
    # Watchdog and uninstall/verify-otp are helper modes — allow multiple.
    # All other modes (service + tray) must be singletons.
    if not args.watchdog and not args.uninstall and not args.verify_otp:
        mutex_name = "Global\\SentraGuard_Tray" if args.tray else "Global\\SentraGuard_Service"
        if not _acquire_mutex(mutex_name):
            log('WARN', f"Another instance is already running ({mutex_name}). Exiting.")
            sys.exit(0)

    # Elevate for uninstall if not already admin
    if args.uninstall and not is_admin():
        try:
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
            if WINDLL:
                WINDLL.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                return
        except Exception as e:
            log('WARN', f"Could not self-elevate for uninstall: {e}")

    # Configure SSL and auth globals (network module)
    _net._ssl_context = ssl.create_default_context()
    if args.no_verify_ssl:
        _net._ssl_context.check_hostname = False
        _net._ssl_context.verify_mode = ssl.CERT_NONE
        log('WARN', 'SSL certificate verification is DISABLED.')
    _net.AGENT_AUTH_TOKEN = args.token
    pin_env = os.environ.get("PINNED_CERT_SHA256")
    _net.PINNED_CERT_SHA256 = (args.cert_sha256 or pin_env or "").lower() or None

    install_root = resolve_install_root(args.install_dir)
    state = load_state()

    if args.server == 'https://localhost:8000' and state.get("server"):
        args.server = state.get("server")
    server = args.server.rstrip('/')

    # Watchdog subprocess mode
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

    # Wait for any in-progress binary swap to complete
    _startup_lock = install_root / SWAP_LOCK_FILE
    if _startup_lock.exists():
        log("INFO", "Swap lock detected at startup — waiting for update to finish...")
        for _ in range(30):
            time.sleep(2)
            if not _startup_lock.exists():
                break
        if _startup_lock.exists():
            # Lock still present after 60 s — the swap helper likely crashed.
            # Force-remove it so startup is not permanently blocked.
            try:
                _startup_lock.unlink()
                log("WARN", "Swap lock forcibly removed after 60 s timeout (stale lock).")
            except Exception as _e:
                log("WARN", f"Could not remove stale swap lock: {_e}")
        else:
            log("INFO", "Swap lock cleared. Continuing startup.")

        # A swap just completed — the old tray process was killed during the file swap.
        # Use WTSQueryUserToken + CreateProcessAsUser to launch the tray directly into
        # the interactive user's desktop session from SYSTEM (Session 0).
        try:
            _exe = str(resolve_install_root(args.install_dir) / "agent.exe")
            _server = args.server.rstrip("/")
            _ps_script = (
                "Add-Type -TypeDefinition '"
                "using System;using System.Runtime.InteropServices;"
                "public class SgWts2{"
                "[DllImport(\"kernel32.dll\")] public static extern uint WTSGetActiveConsoleSessionId();"
                "[DllImport(\"wtsapi32.dll\")] public static extern bool WTSQueryUserToken(uint s,out IntPtr t);"
                "[DllImport(\"advapi32.dll\",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool DuplicateTokenEx(IntPtr h,uint a,IntPtr p,int i,int t,out IntPtr n);"
                "[DllImport(\"advapi32.dll\",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool CreateProcessAsUser(IntPtr t,string app,string cmd,IntPtr pa,IntPtr ta,bool inh,uint cf,IntPtr env,string dir,ref SI si,out PI pi);"
                "[DllImport(\"kernel32.dll\")] public static extern bool CloseHandle(IntPtr h);"
                "[StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] public struct SI{public int cb;public string res,desk,title;public uint x,y,xs,ys,xc,yc,fa,fl;public short sw,_2;public IntPtr _3,si,so,se;}"
                "[StructLayout(LayoutKind.Sequential)] public struct PI{public IntPtr hp,ht;public uint pid,tid;}"
                "}' -ErrorAction Stop;"
                "$sid=[SgWts2]::WTSGetActiveConsoleSessionId();"
                "$tok=[IntPtr]::Zero;"
                "if([SgWts2]::WTSQueryUserToken($sid,[ref]$tok)){"
                "$dup=[IntPtr]::Zero;"
                "[SgWts2]::DuplicateTokenEx($tok,0x10000000,[IntPtr]::Zero,2,1,[ref]$dup)|Out-Null;"
                "$si=New-Object SgWts2+SI;$si.cb=[System.Runtime.InteropServices.Marshal]::SizeOf($si);$si.desk='winsta0\\default';"
                "$pi=New-Object SgWts2+PI;"
                f"[SgWts2]::CreateProcessAsUser($dup,$null,'`\"{_exe}`\" --tray --server={_server} --no-verify-ssl',[IntPtr]::Zero,[IntPtr]::Zero,$false,0x08000000,[IntPtr]::Zero,$null,[ref]$si,[ref]$pi)|Out-Null;"
                "[SgWts2]::CloseHandle($dup)|Out-Null;[SgWts2]::CloseHandle($tok)|Out-Null}"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                 "-ExecutionPolicy", "Bypass", "-Command", _ps_script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            log("INFO", "WTS tray relaunch triggered after update swap.")
        except Exception as _e:
            log("WARN", f"Could not relaunch tray after swap: {_e}")

    if args.uninstall:
        success = protected_uninstall_flow(server, args.otp, args.service_name, install_root)
        sys.exit(0 if success else 1)

    if args.verify_otp:
        success = protected_uninstall_flow(args.server, args.otp, args.service_name, install_root, verify_only=True)
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

    def ensure_tray_autostart(server_url: str, install_root: Path) -> None:
        try:
            import winreg  # type: ignore
            cmd = build_tray_command(server_url)
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_ALL_ACCESS,
            )
            try:
                winreg.DeleteValue(key, "YourAgentTray")
            except FileNotFoundError:
                pass
            except Exception:
                pass
            try:
                # Clean any other agent.exe entries except SentraGuardTray
                idx = 0
                while True:
                    name, value, _ = winreg.EnumValue(key, idx)
                    if name != "SentraGuardTray" and isinstance(value, str) and "agent.exe" in value.lower():
                        winreg.DeleteValue(key, name)
                        continue
                    idx += 1
            except OSError:
                pass
            winreg.SetValueEx(key, "SentraGuardTray", 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            log('INFO', f'✓ Tray autostart registry key ensured in HKLM: {cmd}')
        except Exception as e:
            log('WARN', f'Could not ensure tray autostart in HKLM: {e}')

    # Detect Windows session (Session 0 = service context)
    session_id = ctypes.c_uint32(0)
    try:
        if WINDLL:
            WINDLL.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        log('INFO', f"Agent Session ID: {session_id.value}")
        if session_id.value == 0 and not dry_run and not args.tray:
            ensure_tray_autostart(server, install_root)
            threading.Thread(target=tray_supervisor_loop,
                             args=(server, install_root), daemon=True).start()
    except Exception:
        pass
    log('INFO', f"Agent PID: {os.getpid()}")
    log('INFO', f"Agent Elevation: {'Administrator' if is_admin() else 'Standard User'}")

    def _run_core() -> None:
        global device_id

        log('INFO', 'Collecting system information…')
        system_info = collect_system_info()
        log('INFO', 'Collecting all local users…')
        all_users = collect_all_users()

        log('INFO', 'Registering device with server…')
        cached_state = load_state()
        device_id = cached_state.get("device_id")
        if device_id:
            log('INFO', f"Resuming as device #{device_id} (cached); refreshing registration.")
        else:
            log('INFO', "No cached device ID — performing first-time registration.")

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
                new_id = resp['device_id']
                if device_id and new_id != device_id:
                    log('WARN', f"Server returned different device_id ({new_id}) than cached ({device_id}). Using server value.")
                device_id = new_id
                ensure_dir(runtime_root())
                update_state(device_id=device_id, agent_version=AGENT_VERSION,
                             last_seen=datetime.utcnow().isoformat() + "Z")
                log('INFO', f"Registered as device #{device_id}")
                break
            else:
                log('WARN', f"Registration failed, retrying in {POLL_INTERVAL}s…")
                time.sleep(POLL_INTERVAL)

        # Platform protections
        if not dry_run:
            start_watchdog_process(server, args.service_name)
            threading.Thread(target=tamper_guard_loop, args=(args.service_name,), daemon=True).start()

        # Interactive shell
        if not dry_run and not args.no_shell:
            start_interactive_shell_thread(server, device_id, args.shell)
        else:
            log('INFO', "Interactive shell disabled (dry-run or --no-shell).")

        # Event log collector
        if not dry_run:
            threading.Thread(target=event_log_collector_thread,
                             args=(server, device_id, hostname), daemon=True).start()
        else:
            log('DRY-RUN', "Skipping event log collection.")

        # Periodic system info refresh
        SYS_INFO_INTERVAL = 60

        def sys_info_refresh_loop():
            from state import load_state, update_state
            while True:
                time.sleep(SYS_INFO_INTERVAL)
                resp = api_call(server, 'POST', '/register', {
                    'hostname': hostname,
                    'ip_address': get_ip(),
                    'system_info': collect_system_info(),
                    'all_users': collect_all_users(),
                    'agent_version': AGENT_VERSION,
                    'install_path': str(install_root),
                })
                if resp and 'device_id' in resp:
                    new_id = resp['device_id']
                    current_device_id = load_state().get('device_id')
                    if current_device_id and new_id != current_device_id:
                        log('WARN', f"Server returned different device_id ({new_id}) than cached ({current_device_id}) on refresh. Updating state.")
                        update_state(device_id=new_id)

        if not dry_run:
            threading.Thread(target=sys_info_refresh_loop, daemon=True).start()

        # Software inventory
        if not dry_run:
            threading.Thread(target=software_inventory_thread,
                             args=(server, device_id), daemon=True).start()
        else:
            log('DRY-RUN', "Skipping software inventory sync.")

        # Activity tracking now runs through the dedicated activity/sync services.
        if dry_run:
            log('DRY-RUN', "Skipping activity tracking.")
        else:
            log('INFO', 'Activity tracking is handled by SentraGuardActivitySvc and SentraGuardSyncSvc.')

        # Patch management (service/Session 0 only, or forced)
        if not dry_run and (session_id.value == 0 or args.force_update_check):
            threading.Thread(target=update_poll_loop,
                             args=(server, device_id, args.service_name, install_root),
                             daemon=True).start()
        elif not dry_run:
            log('DEBUG', f"Patch management disabled in user session (Session ID {session_id.value}).")

        log('INFO', f"Polling for commands every {POLL_INTERVAL}s…")
        main_loop(server, device_id, dry_run)

    if args.tray:
        threading.Thread(target=_run_core, daemon=True).start()
        run_with_tray(server, load_state().get('device_id'), args.tray_open)
        return

    _run_core()


if __name__ == '__main__':
    main()
