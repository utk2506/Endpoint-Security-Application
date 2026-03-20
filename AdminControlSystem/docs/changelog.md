# Admin Control System — Feature Tracking & Changelog

This document tracks the progress of the Admin Control System, including completed features, architectural updates, and the timeline of implementation.

## 🟢 Phase 1: Core System MVP
**Status**: Completed
**Completion Date**: March 13, 2026

### Core Backend Features
- **[2026-03-13 13:13]** Project architecture and directory structure planned (`server`, `agent`, `portal`, `docs`).
- **[2026-03-13 13:14]** **FastAPI Central Server**: Basic backend initialized to handle HTTP REST requests continuously.
- **[2026-03-13 13:14]** **SQLite Database & ORM**: Setup `models.py` with SQLAlchemy for storing Devices, Commands, and Admin Snapshots persistently.
- **[2026-03-13 13:14]** **Device Registration API**: Endpoint `/register` allowing agents to check-in on startup.
- **[2026-03-13 13:14]** **Command Queue API**: Asynchronous tracking where portal queues commands (`/send_command`) and agents fetch them (`/get_command`).

### Agent Features
- **[2026-03-13 13:16]** **Background Polling Agent**: Lightweight Python script (`agent.py`) that polls the server every 5 seconds without third-party dependencies.
- **[2026-03-13 13:16]** **Local Privilege Execution**: Agent accepts 'grant', 'revoke', and 'check' instructions and executes them locally on the machine.
- **[2026-03-13 13:16]** **Dry-Run Mode**: Implemented `--dry-run` flag so IT administrators can safely test the agent without actually modifying Windows groups.

### Portal UI Features
- **[2026-03-13 13:14]** **Premium Dashboard Design**: Vanilla HTML/CSS interface using a modern, dark glassmorphism aesthetic with animated gradients.
- **[2026-03-13 13:14]** **Live Statistics Bar**: Top panel showing real-time counts for Active Devices, Active Admins, and Commands Executed.
- **[2026-03-13 13:14]** **Toast Notifications**: Interactive popup alerts (Success/Error/Info) for all user actions in the portal.
- **[2026-03-13 13:14]** **Command Panel**: Form interface allowing the IT admin to select a target device and trigger 'Check', 'Grant', or 'Revoke' actions for specific usernames.
- **[2026-03-13 13:14]** **Active Admin Table**: Table displaying the current snapshot of local administrators on the selected device, with a "Quick Revoke" shortcut button.
- **[2026-03-13 13:14]** **Command History Log**: Scrollable ledger of the last 50 executed commands, including their status (pending/completed/failed) and timestamp.

## 🟢 Phase 1.1: Robustness & UI Fixes
**Status**: Completed  
**Completion Date**: March 13, 2026

### Features & Fixes Implemented
- **[2026-03-13 17:18]** **Agent Resilience**: Switched the local check command from PowerShell (`Get-LocalGroupMember`) to `net localgroup Administrators` to prevent crashes caused by orphaned Azure AD SIDs.
- **[2026-03-13 17:18]** **UI UX Fix**: Prevented the Command History table from blowing up in height due to massive error outputs by truncating long text.
- **[2026-03-13 17:20]** **Timezone Fix**: Fixed backend API to strictly serialize dates in UTC RFC3339 format with millisecond precision, allowing the frontend JS to correctly render timestamps in the user's local time.
- **[2026-03-13 17:20]** **Real-time UX**: Updated the portal so that clicking "Check Status", "Grant Admin", or "Revoke Admin" immediately reloads the command history rather than waiting for the next 5-second polling cycle.
- **[2026-03-13 17:35]** **Dry-Run Toggle**: Verified that disabling `--dry-run` successfully manages real system admin accounts on the local machine.

## 🟢 Phase 1.2: Identity & Connectivity
**Status**: Completed
**Completion Date**: March 13, 2026

### Features Implemented
- **[2026-03-13 23:05]** **Unique Device Identities (UUIDs)**: Migrated the database schema and application logic to use secure UUID strings (`String(36)`) instead of auto-incrementing integers to ensure robust identification across distributed networks.
- **[2026-03-13 23:10]** **Live Online/Offline Indicators**: Implemented a server-side heartbeat tracking mechanism. The agent updates its `last_seen` timestamp on every poll, and the UI now dynamically displays a green dot (🟢) for online devices and a red dot (🔴) for offline/disconnected devices.

---

## 🟢 Phase 2: Remote Shell Access
**Status**: Completed
**Completion Date**: March 13, 2026

### Features Implemented
- **[2026-03-13 23:45]** **Database Schema Expansion**: Added a `payload` column of type `Text` to the `commands` table to store arbitrary PowerShell scripts.
- **[2026-03-13 23:45]** **Agent Arbitrary Execution**: Enabled the agent to parse the new `shell` action using `subprocess.run(['powershell', '-Command', payload])`.
- **[2026-03-13 23:45]** **Remote Shell UI**: Added a new "Remote Shell Executer" panel to the portal dashboard, allowing IT administrators to input multiline PowerShell scripts and execute them directly on endpoints for software installation or maintenance without navigating to the physical machine.

---

## 🟢 Phase 3: Real-Time Interactive Shell
**Status**: Completed
**Completion Date**: March 13, 2026

### Features Implemented
- **[2026-03-13 23:55]** **WebSocket Relay**: Upgraded the FastAPI backend to support full-duplex WebSocket connections, pairing browser clients with endpoint agents.
- **[2026-03-13 23:55]** **Agent PTY Integration**: Upgraded the agent using `pywinpty` to spawn real Windows Pseudo-Consoles for native interactive command execution.
- **[2026-03-13 23:55]** **Browser xterm.js UI**: Embedded `xterm.js` in a glassmorphism modal to render the PowerShell terminal directly inside the web browser.
- **[2026-03-14 00:05]** **Auto-Sync Prompt**: Synchronized PTY size signaling to automatically draw the terminal prompt upon connection without requiring manual user input.

---

## 🟢 Phase 4: Advanced Command History
**Status**: Completed
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14 04:05]** **Backend Query Filtering**: Enhanced `/commands/history` to dynamically parse `action`, `status`, and `search` query parameters and filter the SQLAlchemy results organically.
- **[2026-03-14 04:10]** **Advanced UI Filters**: Deployed a Search & Filter row above the Command History log, allowing instant text-matching against executed command usernames and outputs.
- **[2026-03-14 04:12]** **Persistent Search State**: Embedded live filter state preservation into the 5-second polling tick so filtering acts seamlessly in real-time.

---

## 🟢 Phase 5: Pagination & Device Filtering
**Status**: Completed
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14 12:15]** **Backend Optimization**: Modified the FastAPI `/commands/history` endpoint to query with `.offset()` and `.limit()` variables based on dynamic frontend queries, optimizing database load and calculating total result matches.
- **[2026-03-14 12:15]** **Device Dropdown**: Appended a specific Device identifier filter menu to isolate operations on large scales.
- **[2026-03-14 12:15]** **Interactive Pagination**: Built a DOM pagination structure at the base of the Command History log with active tracking for standard Previous/Next page navigation without breaking current filters.

---

## 🟢 Command History Enhancement v1.1
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14 12:45]** **Interactive Page Navigation**: Transformed the static pagination text into a functional number input allowing immediate jumps to any page.
- **[2026-03-14 12:45]** **Variable Row Density**: Implemented a "Rows per page" picker permitting data frames of 10, 20, or 50 logged commands at once.
- **[2026-03-14 12:45]** **Backend Asc/Desc Row Sorting**: Wired up all table headers (ID, Device, Action, User, Status, Result, Time) to trigger SQLite bidirectional sorting dynamically via `sort_by` and `sort_dir` parameters.

---

## 🟢 Event Log Monitoring
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14 14:30]** **EventLog Database Model**: New `event_logs` table with device_id, hostname, username, event_id, event_name, log_source, timestamp, message columns.
- **[2026-03-14 14:30]** **Agent EventLogCollector**: Background collector using PowerShell `Get-WinEvent` to query 58 specific Event IDs from Security/System/Application logs every 60 seconds with incremental timestamps and batch POSTing.
- **[2026-03-14 14:30]** **Server API Endpoints**: Three new endpoints — `POST /api/v1/device/logs`, `GET /api/v1/event-logs`, `GET /api/v1/event-logs/summary`.
- **[2026-03-14 14:30]** **Portal UI Panel**: Event Log Monitor stats cards (Total Events, Logins, Logoffs, Crashes, Privilege Events) + Event Log History table with sortable columns, filters, and pagination.

---

## 🟢 Phase 6: System Information Collection
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14 18:07]** **Backend Telemetry Integration**: Extended the `Device` model with a `system_info` column and updated the `/register` and `/devices` APIs to store and transmit hardware JSON blobs.
- **[2026-03-14 18:49]** **Agent Hardware Collector**: Implemented `collect_system_info()` using a robust PowerShell script to query WMI for Hostname, User, OS, Uptime, CPU (name, cores, load), RAM (total, used, free), Disks, and all physical Network adapters (including offline LAN/Wi-Fi MACs).
- **[2026-03-14 18:58]** **Real-Time Telemetry Refresh**: Tuned the agent background thread to refresh and re-submit device system info every 10 seconds (optimized from 10 minutes).
- **[2026-03-14 19:07]** **Premium System Info UI**: Deployed a new "System Info" button in the Command Panel, triggering an animated glassmorphism modal with color-shifting progress bars (Green/Yellow/Red) for visualizing hardware utilization.
- **[2026-03-14 19:11]** **Auto-Updating UI Modal**: Implemented a dynamic re-rendering hook in the portal's background polling loop, allowing the System Info modal to update its metrics live on screen every 5 seconds while open.

---

## 🟢 Phase 7: Time-Based Admin Access Auto-Revoke
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14]** **Database Optimization**: Added `expires_at` (DateTime) and `auto_revoked` (Boolean) to the `Command` table.
- **[2026-03-14]** **Server Background Scheduler**: Created `_auto_revoke_loop` thread running every 15 seconds to automatically queue Revoke commands for expired timed grants, ensuring secure auto-revocation even if the portal is closed.
- **[2026-03-14]** **Time-Based Granting UI**: Added an optional `datetime-local` input in the Command Panel to pick a future expiry time when granting admin access.
- **[2026-03-14]** **Live Countdown Feedback**: Modified the History Table to render live countdown badges (e.g. `⏱ 2h 15m`) for timed grants, and automatically update them to `✅ Auto-Revoked` once the system scheduler processes them.

---

## 🟢 Phase 8: Smart User Picker and Role-Aware Grant/Revoke
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14]** **Agent Local User Sync**: Updated `agent.py` so PowerShell dynamically fetches a list of every single local user account (`Get-LocalUser`) on system boot and every 10 seconds.
- **[2026-03-14]** **Smart UI Selection**: Replaced the free-text `Username` box with a drop-down list of all local users populated directly from the connected endpoint.
- **[2026-03-14]** **Role-Aware Logic Guards**: Programmed the frontend so that if a selected user is *not* an admin, "Revoke" is automatically disabled. If a user *is* an admin, "Grant" is automatically disabled, minimizing operational errors.

---

## 🟢 Phase 9: Enhanced History Tracking & Create User Feature
**Status**: Completed  
**Completion Date**: March 14, 2026

### Features Implemented
- **[2026-03-14]** **New User Creation Engine**: Added `execute_create_user(username, password)` to the Python agent, allowing it to seamlessly build new standard local accounts using PowerShell.
- **[2026-03-14]** **Password Obfuscation**: Modified `/commands/history` API logic so plaintext passwords sent during user creation are masked as `***` in the backend payload response.
- **[2026-03-14]** **On-Demand User UI Form**: Created a floating modal via a new `➕ Create User` button in the UI for rapid endpoint account deployment.
- **[2026-03-14]** **Granular History Auditing**: Augmented the frontend History Table to visibly tag grant durations (`15m grant` vs `Permanent`) and flag automatic actions (`🤖 System Auto-Revoke`), creating a fully transparent audit trail.

---

## 🟢 Phase 10: Remote User Notifications
**Status**: Completed  
**Completion Date**: March 15, 2026

### Features Implemented
- **[2026-03-15]** **Notification Campaign Scheduler**: Added a new `NotificationCampaign` database table and a background server thread that automatically queues recurring popup messages to endpoints at configurable time intervals.
- **[2026-03-15]** **Single-Fire Notification**: One-off popup messages can be sent instantly to all or specific logged-in users without creating a repeating schedule.
- **[2026-03-15]** **Repeating Notification Mode**: Supports scheduling a start time, an end time, and a repeat interval (e.g., every 5 minutes) for persistent nagging. The server loop automatically cancels expired campaigns.
- **[2026-03-15]** **Windows `msg.exe` Integration**: Agent uses native Windows messaging tools to display a system pop-up on any live user session without requiring additional software.
- **[2026-03-15]** **Campaign Manager UI**: The portal shows a live table of all active recurring campaigns with a "Cancel" button to immediately stop a specific campaign.
- **[2026-03-15]** **Action Allow List Fix**: The `/send_command` backend endpoint now properly validates and permits `notify` and `create_user` as legitimate actions.

---

## 🟢 Phase 11: Authentication & Security
**Status**: Completed  
**Completion Date**: March 16, 2026

### Features Implemented
- **[2026-03-16]** **Secure Login Portal**: Introduced an authenticated, premium glassmorphism login gateway blocking unauthorized access to the IT dashboard.
- **[2026-03-16]** **JWT Authorization**: Configured FastAPI to issue and validate secure JSON Web Tokens (JWT), ensuring all endpoints (like `/devices`, `/commands`) are fully protected.
- **[2026-03-16]** **Encrypted Admin Accounts**: Expanded the backend schema with a `User` model, securely storing hashed passwords using the robust `bcrypt` algorithm.
- **[2026-03-16]** **Admin Provisioning Utility**: Created a `create_admin.py` standalone tool to easily generate root administrative accounts for initial setup.
- **[2026-03-16]** **Automatic Token Rejection**: Frontend automatically redirects users to the login page when encountering `401 Unauthorized` API responses.

---

## 🟢 Phase 12: Security Hardening & Agent Enhancement
**Status**: Completed  
**Completion Date**: March 16, 2026

### Features Implemented
- **[2026-03-16]** **HTTPS / TLS Encryption**: Added `generate_cert.py` to auto-create a self-signed SSL certificate. The server now starts with `--ssl-keyfile`/`--ssl-certfile` flags and the agent connects securely over `https://` with a `--no-verify-ssl` option for development.
- **[2026-03-16]** **Role-Based Access Control (RBAC)**: Introduced `admin` and `viewer` roles on the `User` model. A `require_admin` dependency gates all destructive endpoints (`/send_command`, notifications). Viewer users see a read-only portal — action buttons are visually disabled with a tooltip.
- **[2026-03-16]** **Audit Log Export (CSV / PDF)**: New portal toolbar buttons trigger `GET /api/v1/audit/export/csv` and `GET /api/v1/audit/export/pdf` to download a full command history export for compliance reporting (up to 500 rows for PDF, unlimited for CSV).
- **[2026-03-16]** **Agent System Tray Icon**: The agent now supports a `--tray` flag using `pystray` + `Pillow`. When enabled, a shield-style icon appears in the Windows taskbar notification area with a right-click menu: **Status**, **Open Log**, and **Exit**.

---

## 🟡 Pending / Future Phases
**Status**: Not Started

### Planned Features
- Role-based Access Control (RBAC)
- Audit Logging export (CSV/PDF)
- System tray icon for the Agent
    