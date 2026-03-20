# How to Patch and Update the Endpoint Agent

This guide explains how to release new updates to your `YourAgent` software.

## 1. Edit the Code
Make your changes directly in `agent.py` or associated files. When you are ready for a new release, make sure to update the `AGENT_VERSION` variable at the top of `agent.py`.

## 2. Compile the Executables
We have provided an automated build script to package your python file and generate the setup file.
1. Open a Command Prompt or PowerShell window in `AdminControlSystem\agent`.
2. Run `build.bat`.
3. The script will:
   - Install required Python dependencies.
   - Download `nssm.exe` (if missing) for service registration.
   - Compile `agent.py` into `agent.exe` via PyInstaller.
   - Run Inno Setup Compiler (`ISCC.exe`) on `agentsetup.iss`.
4. Wait for it to finish. Your new installer will be located in the `Output` folder as `agentsetup.exe`.

## 3. Deployment
Upload the newly generated `agentsetup.exe` to your portal's deployment section or push it via your automatic updater mechanism. 

## Special Uninstall Instructions (OTP Protection)
This installer uses a **custom uninstaller**. Clicking "Uninstall" in the Control Panel does *not* run a standard uninstaller—it runs `agent.exe --uninstall`. 
- `agent.exe` will launch a GUI prompt asking the user for an OTP.
- The OTP is verified against your server API (`/verify-uninstall`).
- Once verified, the service is stopped, deleted, and the program folder removes itself.
