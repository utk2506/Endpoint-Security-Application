# Admin Control System — Architecture

## System Overview

The Admin Control System is a centralized solution for managing temporary
administrator access on company computers. It replaces ad-hoc admin grants
that are often forgotten and never revoked.

```
    ┌──────────────┐       REST API       ┌──────────────────┐
    │  Portal (UI) │ ──────────────────►  │  Central Server  │
    │  HTML + JS   │ ◄──────────────────  │  Python/FastAPI  │
    └──────────────┘                      │  SQLite DB       │
                                          └────────┬─────────┘
                                                   │
                                          HTTP polling (5s)
                                                   │
                                          ┌────────▼─────────┐
                                          │   Agent Service   │
                                          │   Python script   │
                                          │   (on each PC)    │
                                          └──────────────────┘
```

## Components

### 1. Central Server (`server/app.py`)

- **Framework**: FastAPI
- **Database**: SQLite via SQLAlchemy ORM
- **Responsibilities**:
  - Register devices
  - Queue commands (grant / revoke / check)
  - Serve command queues to agents
  - Store command results and admin snapshots
  - Serve the portal UI as static files

### 2. Portal (`portal/index.html` + `dashboard.js`)

- Pure HTML + JavaScript (no frameworks)
- Communicates with the server via `fetch()` REST calls
- Auto-refreshes every 5 seconds
- Features:
  - Device selector
  - Grant / Revoke / Check actions
  - Live admin user list
  - Command history log
  - Statistics dashboard

### 3. Agent (`agent/agent.py`)

- Pure Python (no external dependencies)
- Runs on each managed PC
- On startup: registers the device with the server
- Polls `GET /get_command/{device_id}` every 5 seconds
- Executes Windows commands via `subprocess`:
  - `net localgroup Administrators {user} /add`  — grant
  - `net localgroup Administrators {user} /delete` — revoke
  - `net localgroup Administrators` — check/list
- Reports results back via `POST /command_result`
- Supports `--dry-run` mode for safe testing

## API Reference

| Endpoint                   | Method | Purpose                              |
|----------------------------|--------|--------------------------------------|
| `/register`                | POST   | Register or update a device          |
| `/devices`                 | GET    | List all registered devices          |
| `/send_command`            | POST   | Queue a command for a device         |
| `/get_command/{device_id}` | GET    | Agent fetches next pending command   |
| `/command_result`          | POST   | Agent reports command execution      |
| `/admin_list/{device_id}`  | GET    | Latest admin snapshot for a device   |
| `/commands/history`        | GET    | Recent command log (default 50)      |

## Database Schema

### `devices`
| Column        | Type     | Notes                |
|---------------|----------|----------------------|
| id            | INTEGER  | Primary key          |
| hostname      | VARCHAR  | Unique               |
| ip_address    | VARCHAR  |                      |
| registered_at | DATETIME | Auto-set             |
| last_seen     | DATETIME | Updated on heartbeat |

### `commands`
| Column      | Type     | Notes                                   |
|-------------|----------|-----------------------------------------|
| id          | INTEGER  | Primary key                             |
| device_id   | INTEGER  | FK → devices                            |
| action      | VARCHAR  | grant / revoke / check                  |
| username    | VARCHAR  | Nullable (null for check)               |
| status      | VARCHAR  | pending → executing → completed / failed|
| result      | TEXT     | Execution output                        |
| created_at  | DATETIME |                                         |
| executed_at | DATETIME |                                         |

### `admin_snapshots`
| Column      | Type     | Notes                    |
|-------------|----------|--------------------------|
| id          | INTEGER  | Primary key              |
| device_id   | INTEGER  | FK → devices             |
| admin_users | TEXT     | JSON list of usernames   |
| captured_at | DATETIME |                          |

## Running the System

### 1. Start the Server
```powershell
cd AdminControlSystem\server
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

### 2. Start the Agent (on each PC)
```powershell
cd AdminControlSystem\agent
# Normal mode (requires admin terminal):
python agent.py --server http://SERVER_IP:8000

# Safe testing mode:
python agent.py --server http://SERVER_IP:8000 --dry-run
```

### 3. Open the Portal
Navigate to `http://SERVER_IP:8000` in a web browser.

## Security Notes (Phase 5)

The current prototype has no authentication. Future phases will add:
- Device authentication tokens
- HTTPS/TLS
- Audit logging
- Role-based access control
- Alerts for unauthorized admin changes
