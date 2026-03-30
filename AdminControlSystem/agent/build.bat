@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   SentraGuard ^| Full Build Pipeline v1.1.0
echo   Builds: agent.exe + activityservice.exe + syncservice.exe
echo   Output: SentraGuardSetup.exe
echo ============================================================

echo.
echo [1/6] Installing Python dependencies...
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pyinstaller pystray Pillow psutil websockets requests pywinpty pynput pywin32

if errorlevel 1 (
    echo [ERROR] pip install failed. Ensure Python 3.10+ is installed and on PATH.
    exit /b 1
)
echo [OK] Dependencies installed.

echo.
echo [2/6] Downloading NSSM (Non-Sucking Service Manager)...
if not exist nssm.exe (
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip' -UseBasicParsing"
    powershell -NoProfile -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath 'nssm_temp' -Force"
    copy /Y "nssm_temp\nssm-2.24\win64\nssm.exe" "nssm.exe" >nul
    rmdir /S /Q nssm_temp
    del nssm.zip
    echo [OK] nssm.exe downloaded.
) else (
    echo [OK] nssm.exe already present.
)

echo.
echo [3/6] Compiling agent.exe (SentraGuard Core Service)...
pyinstaller --clean --onefile --console ^
    --name agent ^
    --distpath dist_sg\agent ^
    --hidden-import winpty ^
    --hidden-import pywinpty ^
    --hidden-import win32serviceutil ^
    --hidden-import win32event ^
    --collect-all winpty ^
    --collect-all pywinpty ^
    agent.py

if not exist "dist_sg\agent\agent.exe" (
    echo [ERROR] agent.exe was not produced. Check PyInstaller output above.
    exit /b 1
)
echo [OK] agent.exe built successfully.

echo.
echo [4/6] Compiling activityservice.exe (SentraGuard Activity Collection Service)...
pyinstaller --clean --onefile --console ^
    --name activityservice ^
    --distpath dist_sg\activityservice ^
    --hidden-import win32api ^
    --hidden-import win32con ^
    --hidden-import win32gui ^
    --hidden-import psutil ^
    --hidden-import ctypes ^
    --hidden-import pynput ^
    --hidden-import pynput.mouse ^
    --hidden-import pynput.keyboard ^
    --hidden-import pynput.mouse._win32 ^
    --hidden-import pynput.keyboard._win32 ^
    activityservice.py

if not exist "dist_sg\activityservice\activityservice.exe" (
    echo [ERROR] activityservice.exe was not produced. Check PyInstaller output above.
    exit /b 1
)
echo [OK] activityservice.exe built successfully.

echo.
echo [5/6] Compiling syncservice.exe (SentraGuard Activity Sync Service)...
pyinstaller --clean --onefile --console ^
    --name syncservice ^
    --distpath dist_sg\syncservice ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    syncservice.py

if not exist "dist_sg\syncservice\syncservice.exe" (
    echo [ERROR] syncservice.exe was not produced. Check PyInstaller output above.
    exit /b 1
)
echo [OK] syncservice.exe built successfully.

echo.
echo ============================================================
echo   Build Summary
echo ============================================================
echo   dist_sg\agent\agent.exe
echo   dist_sg\activityservice\activityservice.exe
echo   dist_sg\syncservice\syncservice.exe
echo ============================================================

echo.
echo [6/6] Packaging installer with Inno Setup...

set ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if not exist "%ISCC_PATH%" (
    set ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe
)

if exist "%ISCC_PATH%" (
    "%ISCC_PATH%" agentsetup.iss
    if errorlevel 1 (
        echo [ERROR] Inno Setup compilation failed.
        exit /b 1
    )
    echo.
    echo ============================================================
    echo   Installer: Output_Safe\SentraGuardSetup.exe
    echo   Contains : agent + activityservice + syncservice + nssm
    echo ============================================================
) else (
    echo [!] Inno Setup ISCC.exe not found.
    echo     Install Inno Setup 6 from: https://jrsoftware.org/isinfo.php
    echo     Or open agentsetup.iss manually in Inno Setup Studio.
    echo.
    echo     All EXEs are ready in dist_sg\ folder.
)

echo.
echo Done.
