@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   SentraGuard — Full Build Pipeline
echo ============================================================

echo.
echo [1/5] Installing Python dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller pystray Pillow psutil websockets requests pywinpty pynput

echo.
echo [2/5] Downloading NSSM (Non-Sucking Service Manager) if needed...
if not exist nssm.exe (
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip'"
    powershell -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath 'nssm_temp' -Force"
    copy /Y "nssm_temp\nssm-2.24\win64\nssm.exe" "nssm.exe"
    rmdir /S /Q nssm_temp
    del nssm.zip
)

echo.
echo [3/5] Compiling agent.exe (SentraGuard main service)...
pyinstaller --clean --onefile --console ^
    --name agent ^
    --distpath dist_sg\agent ^
    --hidden-import winpty ^
    --hidden-import pywinpty ^
    --collect-all winpty ^
    --collect-all pywinpty ^
    agent.py

if not exist "dist_sg\agent\agent.exe" (
    echo [ERROR] agent.exe was not produced. Check PyInstaller output above.
    exit /b 1
)
echo [OK] agent.exe built successfully.

echo.
echo [4/5] Compiling activity_service.exe (SentraGuardActivityService)...
pyinstaller --clean --onefile --console ^
    --name activity_service ^
    --distpath dist_sg\activity_service ^
    --hidden-import pynput ^
    --hidden-import pynput.mouse ^
    --hidden-import pynput.keyboard ^
    --hidden-import pynput._util ^
    --hidden-import pynput._util.win32 ^
    --hidden-import pynput.mouse._win32 ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import sqlite3 ^
    --exclude-module winpty ^
    --exclude-module pywinpty ^
    --exclude-module tkinter ^
    --exclude-module pystray ^
    activity_service.py

if not exist "dist_sg\activity_service\activity_service.exe" (
    echo [ERROR] activity_service.exe was not produced. Check PyInstaller output above.
    exit /b 1
)
echo [OK] activity_service.exe built successfully.

echo.
echo ============================================================
echo   Build Summary
echo ============================================================
echo   dist_sg\agent\agent.exe
echo   dist_sg\activity_service\activity_service.exe
echo ============================================================

echo.
echo [5/5] Packaging installer with Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" agentsetup.iss
    if errorlevel 1 (
        echo [ERROR] Inno Setup compilation failed.
        exit /b 1
    )
    echo.
    echo ============================================================
    echo   Installer output: Output_Safe\SentraGuardSetup_New.exe
    echo ============================================================
) else (
    echo [!] Inno Setup ISCC.exe not found at default location.
    echo Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo Or run agentsetup.iss manually in Inno Setup Studio.
    echo.
    echo Build products are ready in dist_sg\ — install Inno Setup to create installer.
)

echo.
echo Done.
