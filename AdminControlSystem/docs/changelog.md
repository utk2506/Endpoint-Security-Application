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

## 🟡 Pending / Future Phases
**Status**: Not Started

### Planned Features
- Authentication and Secure Login for the Portal
- HTTPS/TLS encryption for Agent-Server communication
- Role-based Access Control (RBAC)
- Audit Logging export (CSV/PDF)
- System tray icon for the Agent
