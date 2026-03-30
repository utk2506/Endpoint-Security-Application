"""
syncservice.py — SentraGuard Activity Sync Service

This is the PyInstaller entry point for syncservice.exe.
Installed by Inno Setup as the Windows service "SentraGuardSyncSvc"
via NSSM. Runs as SYSTEM, reads offline activity events from the
local SQLite cache and pushes them to the portal API over HTTPS.

Offline support: If the portal is unreachable, events remain in the
cache and will be retried every SYNC_INTERVAL_SECONDS.

Usage:
  syncservice.exe --server https://yourserver:8000
  syncservice.exe --server https://yourserver:8000 --no-verify-ssl
"""

import sys
import os
import argparse

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from logger import log
from activity_tracker import start_sync_service


def parse_args():
    parser = argparse.ArgumentParser(description="SentraGuard Sync Service")
    parser.add_argument("--server", default="https://localhost:8000",
                        help="Portal server base URL")
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="Disable SSL certificate verification")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.no_verify_ssl:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context

    log("INFO", "=" * 60)
    log("INFO", f"SentraGuard Sync Service — Starting")
    log("INFO", f"Server: {args.server}")
    log("INFO", "=" * 60)

    try:
        start_sync_service(args.server)   # Blocks indefinitely
    except KeyboardInterrupt:
        log("INFO", "SentraGuardSyncSvc: received KeyboardInterrupt — shutting down")
    except Exception as e:
        log("ERROR", f"SentraGuardSyncSvc fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
