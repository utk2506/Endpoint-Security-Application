"""
activityservice.py — SentraGuard Activity Collection Service

This is the PyInstaller entry point for activityservice.exe.
Installed by Inno Setup as the Windows service "SentraGuardActivitySvc"
via NSSM. Runs as SYSTEM, collects user activity events and writes them
to the local SQLite cache at:
  C:\\ProgramData\\SentraGuard\\activity_cache.db

Usage:
  activityservice.exe           (service mode — runs collection loop)
  activityservice.exe --install (install and start via NSSM — done by installer)
"""

import sys
import os
import time  # noqa: F401 — used in main() restart loop

# Ensure the agent directory is on the path when run as a compiled EXE
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from logger import log
from activity_tracker import start_activity_service


def main():
    log("INFO", "=" * 60)
    log("INFO", "SentraGuard Activity Collection Service — Starting")
    log("INFO", "=" * 60)

    consecutive_failures = 0
    while True:
        try:
            start_activity_service()   # Blocks indefinitely; returns only on error
            break  # Clean exit (shouldn't normally happen)
        except (KeyboardInterrupt, SystemExit):
            log("INFO", "SentraGuardActivitySvc: received stop signal — shutting down")
            break
        except BaseException as e:
            consecutive_failures += 1
            wait = min(consecutive_failures * 5, 30)  # 5s, 10s, … up to 30s
            log("ERROR", f"SentraGuardActivitySvc crashed (#{consecutive_failures}): {e} — restarting in {wait}s")
            time.sleep(wait)
            # Reset after recovery
            if consecutive_failures >= 5:
                consecutive_failures = 0


if __name__ == "__main__":
    main()
