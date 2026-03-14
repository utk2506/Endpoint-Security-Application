@echo off
echo ════════════════════════════════════════════
echo   Admin Control System — Starting...
echo ════════════════════════════════════════════

:: Start the Server in a new window
start "ACS Server" cmd /k "cd /d %~dp0server && python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload"

:: Wait 3 seconds for the server to boot
timeout /t 3 /nobreak >nul

:: Start the Agent in a new window
start "ACS Agent" cmd /k "cd /d %~dp0agent && python agent.py --server http://localhost:8000"

echo.
echo   ✓ Server started on http://localhost:8000
echo   ✓ Agent started and connecting...
echo.
echo   Portal: http://localhost:8000
echo ════════════════════════════════════════════
