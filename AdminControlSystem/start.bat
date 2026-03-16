@echo off
echo ════════════════════════════════════════════
echo   Admin Control System — Starting...
echo ════════════════════════════════════════════

:: Generate SSL certificate if not already present
if not exist "%~dp0server\server.crt" (
    echo   Generating self-signed SSL certificate...
    python "%~dp0generate_cert.py"
)

:: Start the Server in a new window (HTTPS)
start "ACS Server" cmd /k "cd /d %~dp0server && python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload --ssl-keyfile server.key --ssl-certfile server.crt"

:: Wait 3 seconds for the server to boot
timeout /t 3 /nobreak >nul

:: Start the Agent in a new window (HTTPS, --no-verify for self-signed cert)
start "ACS Agent" cmd /k "cd /d %~dp0agent && python agent.py --server https://localhost:8000 --no-verify-ssl"

echo.
echo   ✓ Server started on https://localhost:8000  (HTTPS)
echo   ✓ Agent started and connecting...
echo.
echo   Portal: https://localhost:8000
echo ════════════════════════════════════════════
