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

# ── Helpers ─────────────────────────────────────────────────────────────────

def log(level, msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] [{level}]  {msg}")


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
    log('INFO', 'Registering device with server…')
    device_id = None

    while device_id is None:
        resp = api_call(server, 'POST', '/register', {
            'hostname': hostname,
            'ip_address': ip_address,
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

    # ── Polling loop ────────────────────────────────────────────────────
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
