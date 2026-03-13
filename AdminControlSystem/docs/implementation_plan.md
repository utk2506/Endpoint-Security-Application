# Temporary Admin Access Management System — Phase 1

Build a working prototype with three components: a FastAPI server, an HTML/JS portal, and a Python agent that polls for commands and executes them on the local machine.

## Proposed Changes

### Server Component

#### [NEW] [app.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/server/app.py)

FastAPI application with these endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/register` | POST | Register a device (hostname, IP) |
| `/send_command` | POST | Queue a command for a device (grant/revoke/check) |
| `/get_command/{device_id}` | GET | Agent polls for pending commands |
| `/command_result` | POST | Agent posts command execution results |
| `/admin_list/{device_id}` | GET | Portal fetches current admin list for a device |
| `/devices` | GET | List all registered devices |
| `/commands/history` | GET | Recent command history |

CORS enabled so the portal can call the API from the browser.

#### [NEW] [models.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/server/models.py)

SQLite database with SQLAlchemy:

- **devices** — `id`, `hostname`, `ip_address`, `registered_at`, `last_seen`
- **commands** — `id`, `device_id`, `action` (grant/revoke/check), `username`, `status` (pending/executing/completed/failed), `result`, `created_at`, `executed_at`
- **admin_snapshots** — `id`, `device_id`, `admin_users` (JSON list), `captured_at`

#### [NEW] [requirements.txt](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/server/requirements.txt)

`fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`

---

### Portal Component

#### [NEW] [index.html](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/portal/index.html)

Single-page dashboard with:
- Dark-themed premium UI with glassmorphism cards, gradients, and micro-animations
- Device selector (dropdown populated from `/devices`)
- Username input + **Check Status** / **Grant Admin** / **Revoke Admin** buttons
- Live admin list table showing current admins on the selected device
- Command history log
- Status indicators with colour-coded badges (Admin = red, Standard = green)

#### [NEW] [dashboard.js](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/portal/dashboard.js)

All fetch-based API calls, auto-refresh polling (every 5 s), toast notifications, and DOM manipulation logic.

---

### Agent Component

#### [NEW] [agent.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/agent/agent.py)

Python script that:

1. On startup, registers the device via `POST /register`
2. Enters a loop (every 5 seconds):
   - `GET /get_command/{device_id}` — fetch next pending command
   - If a command exists, execute it via `subprocess`:
     - **grant**: `net localgroup Administrators {username} /add`
     - **revoke**: `net localgroup Administrators {username} /delete`
     - **check**: `net localgroup Administrators` → parse member list
   - `POST /command_result` — send result back to server
3. Handles errors gracefully and logs activity to console

---

### Documentation

#### [NEW] [architecture.md](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/docs/architecture.md)

Markdown doc describing the system architecture, data flow, and API reference.

## Verification Plan

### Automated Tests

1. **Start the server**
   ```
   cd c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server
   pip install -r requirements.txt
   python -m uvicorn app:app --host 0.0.0.0 --port 8000
   ```
2. **API smoke tests via browser subagent**
   - Open `http://localhost:8000/docs` (FastAPI auto-docs) and confirm all endpoints are listed
   - Open the portal at `http://localhost:8000` (served via FastAPI static mount) or open `portal/index.html` directly

### Manual Verification (using the portal)

1. Open the portal in a browser
2. The device dropdown should show the agent's device once the agent registers
3. Enter a username → click **Check Status** → confirm the admin list is fetched and displayed
4. Click **Grant Admin** → confirm the command is queued, agent picks it up, and status updates
5. Click **Revoke Admin** → same flow
6. Verify the command history log updates in real time

> [!IMPORTANT]
> The agent executes `net localgroup` commands that require **Administrator privileges**. During testing, run the agent from an elevated (Run as Administrator) terminal. You can also test with a mock/dry-run flag if you prefer not to modify real admin groups.

---

## Phase 2 — Remote Shell Access

To enable remote software installation and uninstallation, a remote shell capability will be added.

### Proposed Changes

#### [MODIFY] [models.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/server/models.py)
- **commands** table: Add a new `payload` column (`Text`, nullable) to store the raw PowerShell command script.
- *Note:* The database will be rebuilt to apply this schema change cleanly.

#### [MODIFY] [app.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/server/app.py)
- **SendCommandRequest**: Add `payload: Optional[str] = None`.
- **send_command** and **get_command**: Update logic to process the new `shell` action and store/retrieve the `payload`.

#### [MODIFY] [agent.py](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/agent/agent.py)
- Add `execute_shell(payload, dry_run=False)` method.
- The agent will execute the `payload` securely using `subprocess` and PowerShell, capturing stdout/stderr and sending the results back via `/command_result`.

#### [MODIFY] [index.html](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/portal/index.html) & [dashboard.js](file:///c:/Users/ITSupport/Downloads/New%20folder%20(9)/AdminControlSystem/portal/dashboard.js)
- **Portal UI**: Add a new "Remote Shell" tab/panel with a multi-line text area for script input.
- **Actions**: Add a `runShellCommand()` frontend function.

### Verification Plan
1. Reset database to apply schema changes.
2. Restart server and agent.
3. Use the new Remote Shell UI to execute a benign command like `Get-Process` or `echo "Hello World"`.
4. Verify the output displays correctly within the Command History without crashing the table.
