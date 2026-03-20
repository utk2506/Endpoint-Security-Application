@echo off
REM ══════════════════════════════════════════════════════════════════
REM  Admin Control System — Server Startup Script
REM  Binds to ALL network interfaces (0.0.0.0) so agents can connect
REM  from any network — local OR over the internet.
REM
REM  First-time setup:
REM    1. Generate cert:  python generate_cert.py
REM    2. Set token:      set AGENT_SHARED_TOKEN=your-secret-token
REM    3. Run this file:  start.bat
REM
REM  For internet access:
REM    - Open port 8000 (or 443) in your firewall / router
REM    - Use a real TLS cert (Let's Encrypt) for production
REM    - See INTERNET_SETUP.md for full guide
REM ══════════════════════════════════════════════════════════════════

setlocal

REM ── Configuration ──────────────────────────────────────────────────
set HOST=0.0.0.0
set PORT=8000
set WORKERS=1
set SSL_CERT=server.crt
set SSL_KEY=server.key

REM ── Derive paths ───────────────────────────────────────────────────
set SCRIPT_DIR=%~dp0
set SERVER_DIR=%SCRIPT_DIR%server

REM ── Change to server directory ─────────────────────────────────────
cd /d "%SERVER_DIR%"

REM ── Install dependencies (silent) ──────────────────────────────────
echo [ACS] Installing server dependencies...
python -m pip install -r requirements.txt --quiet

REM ── Check for SSL certificate ──────────────────────────────────────
if not exist "%SSL_CERT%" (
    echo [ACS] No certificate found. Generating self-signed cert...
    python "%SCRIPT_DIR%generate_cert.py"
)

REM ── Launch Uvicorn bound to all interfaces ─────────────────────────
echo.
echo ╔═══════════════════════════════════════════════════╗
echo ║        Admin Control System - Server              ║
echo ╠═══════════════════════════════════════════════════╣
echo ║  Listening on: https://%HOST%:%PORT%           ║
echo ║  Portal URL  : https://localhost:%PORT%/portal/    ║
echo ║  Agents on LAN : https://[YOUR_LAN_IP]:%PORT%      ║
echo ║  Agents on NET : https://[YOUR_PUBLIC_IP]:%PORT%   ║
echo ║                                                   ║
echo ║  Press Ctrl+C to stop                             ║
echo ╚═══════════════════════════════════════════════════╝
echo.

python -m uvicorn app:app ^
    --host %HOST% ^
    --port %PORT% ^
    --workers %WORKERS% ^
    --ssl-certfile %SSL_CERT% ^
    --ssl-keyfile %SSL_KEY% ^
    --log-level info ^
    --access-log

endlocal
pause
