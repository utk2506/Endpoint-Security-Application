# Portal Patch How-To (One-Pager)

Use this to build a new agent EXE and publish it through the admin portal.

## 1) Bump the agent version
1. Edit `agent/agent.py` and set `AGENT_VERSION = "<new_version>"` (e.g., `1.1.4`).
2. Commit the change if you keep versioning in git.

## 2) Build the Windows agent binary
From `AdminControlSystem/agent` in a regular (non-admin) PowerShell:
```powershell
./build_installer.ps1 -Version <new_version>
```
Outputs we care about:
- `dist/YourAgent.exe` (main agent)  ← this is the file to upload to the portal.
Optional: `dist/YourAgentSetup.exe` and `dist/YourAgentUninstall.exe` if you need installers.

## 3) Upload via the admin portal
1. Open the portal -> Endpoint Maintenance -> **Upload Agent Update**.
2. Version: enter the same `<new_version>` you set in `agent.py`.
3. Binary: choose `dist/YourAgent.exe`.
4. Release notes: optional, short text.
5. Click Upload. The portal creates/activates the new version in the database and serves the file at `/downloads/agent-<new_version>.exe`.

## 4) Verify on a device
- In the portal, Device Patch Status should show Latest release = `<new_version>` and no “Update available”.
- On the device, `C:\Program Files\YourAgent\agent_state.json` should show `"agent_version": "<new_version>"` after one heartbeat (or after restarting the service).

## 5) If the swap ever fails (rare)
- The helper script already stops the service and kills stray agent processes before copying.
- If you need a manual nudge: `Stop-Service YourAgent -Force; Start-Sleep 3; Start-Service YourAgent`.

That’s all—repeat these steps for each release.***
