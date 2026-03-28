@echo off
:: create_task_applylatest.cmd
:: Run by Inno Setup [Run] section at install time.
:: Registers (or replaces) the SentraGuard\ApplyLatest scheduled task that
:: applies staged agent updates hourly, running as SYSTEM with highest privileges.

setlocal enabledelayedexpansion

:: Use the directory containing this script as the install root
set "APPDIR=%~dp0"
:: Remove trailing backslash from APPDIR so paths look clean
if "%APPDIR:~-1%" == "\" set "APPDIR=%APPDIR:~0,-1%"

set "SCRIPT=%APPDIR%\apply_latest.ps1"
set "TASKNAME=SentraGuard\ApplyLatest"

:: Delete any existing version of the task first (ignore errors)
schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

:: Create the task: hourly, SYSTEM account, highest privileges
schtasks /Create /F ^
  /RU SYSTEM /RL HIGHEST ^
  /TN "%TASKNAME%" ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File \"%SCRIPT%\"" ^
  /SC HOURLY /MO 1

if %ERRORLEVEL% NEQ 0 (
    echo [SentraGuard] WARNING: Failed to create scheduled task "%TASKNAME%". Exit code: %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo [SentraGuard] Scheduled task "%TASKNAME%" created successfully.

:: Trigger it immediately so any pending staged update is applied right after install
schtasks /Run /TN "%TASKNAME%" >nul 2>&1

endlocal
exit /b 0
