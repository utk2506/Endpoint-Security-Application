"""
watchdog.py — Watchdog process and tamper guard.
"""

import os
import shutil
import subprocess
import time

from config import (
    WATCHDOG_INTERVAL, SWAP_LOCK_FILE,
    DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW,
)
from logger import log
from network import AGENT_AUTH_TOKEN
from updater import current_binary_path


# ── Service helpers ───────────────────────────────────────────────────────────

def is_service_running(name: str) -> bool:
    try:
        out = subprocess.check_output(["sc", "query", name], creationflags=CREATE_NO_WINDOW)
        return b"RUNNING" in out
    except Exception:
        return False


def stop_service(name: str) -> None:
    for cmd in [["nssm", "stop", name], ["sc", "stop", name]]:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except Exception:
            continue


def restart_service(name: str) -> None:
    for cmd in [["nssm", "restart", name], ["sc", "start", name]]:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            if is_service_running(name):
                return
        except Exception:
            continue


# ── Watchdog ──────────────────────────────────────────────────────────────────

def start_watchdog_process(server_url: str, service_name: str) -> None:
    """Spawn a detached watchdog process that will restart the service if it dies."""
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
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        log("INFO", "Watchdog process spawned.")
    except Exception as e:
        log("WARN", f"Failed to start watchdog: {e}")


def watchdog_loop(parent_pid: int, service_name: str, server_url: str) -> None:
    """Monitor the SERVICE (not PID) and restart as needed. Respects swap lock."""
    log("INFO", f"Watchdog started (service={service_name})")
    install_root = current_binary_path().parent
    lock_file = install_root / SWAP_LOCK_FILE

    if lock_file.exists():
        log("INFO", "Swap lock detected on watchdog startup — update may be in progress.")

    while True:
        if lock_file.exists():
            log("INFO", "Swap in progress. Watchdog waiting...")
            time.sleep(WATCHDOG_INTERVAL)
            continue

        if not is_service_running(service_name):
            log("WARN", "Agent service not running — attempting restart.")
            restart_service(service_name)
            if not is_service_running(service_name):
                try:
                    exe = current_binary_path()
                    cmd = [str(exe), "--server", server_url]
                    if AGENT_AUTH_TOKEN:
                        cmd.append(f"--token={AGENT_AUTH_TOKEN}")
                    subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
                    log("INFO", "Agent launched directly as fallback after service restart failed.")
                except Exception:
                    pass

        time.sleep(WATCHDOG_INTERVAL)


# ── Tamper guard ──────────────────────────────────────────────────────────────

def tamper_guard_loop(service_name: str) -> None:
    """Lightweight guard: restarts service and restores binary if tampered."""
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
