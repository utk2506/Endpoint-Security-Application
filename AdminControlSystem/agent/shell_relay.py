"""
shell_relay.py — Remote interactive shell via WebSocket + WinPTY/subprocess PTY.
"""

import asyncio
import os
import subprocess
import threading

import websockets  # type: ignore

from config import HAS_PYWINPTY, CREATE_NO_WINDOW
from logger import log
import network as _net
from network import powershell_available, AGENT_AUTH_TOKEN

# Import PtyProcess/Backend only if available
try:
    from winpty import PtyProcess, Backend  # type: ignore
except ImportError:
    try:
        from pywinpty import PtyProcess, Backend  # type: ignore
    except ImportError:
        PtyProcess = None
        Backend = None


async def interactive_shell_loop(server_url: str, device_id: str, shell_pref: str = "cmd") -> None:
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

            connect_kwargs: dict = {"origin": server_url}
            # Read _ssl_context from the network module at connection time (not import time)
            # so that the --no-verify-ssl context set in main() is always picked up.
            live_ssl_ctx = _net._ssl_context
            if ws_url.startswith("wss://") and live_ssl_ctx:
                connect_kwargs["ssl"] = live_ssl_ctx
            if AGENT_AUTH_TOKEN:
                connect_kwargs["extra_headers"] = {"Authorization": f"Bearer {AGENT_AUTH_TOKEN}"}

            async with websockets.connect(ws_url, **connect_kwargs) as ws:  # type: ignore
                loop = asyncio.get_event_loop()
                stop_event = threading.Event()
                clean_env = os.environ.copy()
                for k in ['PYTHONPATH', 'PYTHONHOME']:
                    clean_env.pop(k, None)

                # --- Spawn: WinPTY (priority) ---
                if HAS_PYWINPTY and PtyProcess is not None:
                    try:
                        pty_proc = PtyProcess.spawn(shell_argv, backend=Backend.WinPTY, cwd="C:\\", env=clean_env)
                        is_pty = True
                        log('INFO', f"Connected to Relay — Started WinPTY Shell (PID: {pty_proc.pid})")
                    except Exception as e:
                        log('WARN', f"WinPTY spawn failed: {e}. Falling back to Subprocess.")
                        HAS_PYWINPTY = False

                # --- Spawn: subprocess fallback ---
                if pty_proc is None:
                    pty_proc = subprocess.Popen(
                        shell_argv,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env=clean_env,
                        cwd="C:\\",
                        bufsize=0,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    is_pty = False
                    log('INFO', f"Connected to Relay — Started UNBUFFERED Subprocess Shell (PID: {pty_proc.pid})")

                output_queue: asyncio.Queue = asyncio.Queue()

                def _pty_reader():
                    log("DEBUG", f"Shell reader thread started for {'PTY' if is_pty else 'Subprocess'} PID {pty_proc.pid}")
                    while not stop_event.is_set():
                        try:
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
                                data = os.read(pty_proc.stdout.fileno(), 4096)
                                if not data:
                                    break
                            asyncio.run_coroutine_threadsafe(output_queue.put(data.decode('utf-8', errors='replace')), loop)
                        except Exception as e:
                            log("DEBUG", f"Shell reader exception: {repr(e)}")
                            break
                    asyncio.run_coroutine_threadsafe(output_queue.put(None), loop)
                    log("DEBUG", "Shell reader thread exiting.")

                threading.Thread(target=_pty_reader, daemon=True).start()

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

                RESIZE_PREFIX = '\x1bPTYR:'

                async def _forward_input():
                    try:
                        while True:
                            msg = await ws.recv()
                            if isinstance(msg, str) and msg.startswith(RESIZE_PREFIX):
                                if is_pty:
                                    try:
                                        parts = msg[len(RESIZE_PREFIX):].split(';')
                                        if len(parts) == 2:
                                            pty_proc.set_winsize(int(parts[0]), int(parts[1]))
                                    except Exception:
                                        pass
                            else:
                                if isinstance(msg, str):
                                    msg = msg.encode('utf-8')
                                if is_pty:
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
                    pty_proc.terminate()
                except Exception:
                    pass
        await asyncio.sleep(5)


def start_interactive_shell_thread(server_url: str, device_id: str, shell_pref: str = "cmd") -> None:
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(interactive_shell_loop(server_url, device_id, shell_pref))

    threading.Thread(target=run, daemon=True).start()
