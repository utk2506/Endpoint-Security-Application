@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [1/4] Installing Python dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller pystray Pillow psutil websockets requests pywinpty

echo [2/4] Downloading NSSM (Non-Sucking Service Manager) if needed...
if not exist nssm.exe (
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip'"
    powershell -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath 'nssm_temp' -Force"
    copy /Y "nssm_temp\nssm-2.24\win64\nssm.exe" "nssm.exe"
    rmdir /S /Q nssm_temp
    del nssm.zip
)

echo [3/4] Compiling agent.py with PyInstaller...
pyinstaller --clean --onefile --console --name agent --hidden-import winpty --hidden-import pywinpty --collect-all winpty --collect-all pywinpty agent.py

echo [4/4] Compiling agentsetup.exe with Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" agentsetup.iss
    echo Build complete! Installer is located in Output\agentsetup.exe
) else (
    echo [!] Inno Setup ISCC.exe not found at default location.
    echo Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo Or run agentsetup.iss manually in Inno Setup Studio.
)
