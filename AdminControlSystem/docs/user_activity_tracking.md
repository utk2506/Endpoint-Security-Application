# User Activity Tracking – Draft Design

## Goal
Capture per-device user activity (active window focus, idle time, high‑level click/keyboard volume) and surface it in the portal via a new left-nav tab with reporting and filters. Initial scope avoids keylogging/keystroke content; only metadata is stored.

## Proposed Data
- `device_id`
- `timestamp_utc`
- `active_window_title`
- `process_name`
- `idle_seconds` (time since last input)
- `input_counts` (clicks, keypresses per sample interval; counts only, no content)

## Agent (Windows)
- Background sampler every 15s:
  - `GetForegroundWindow` + `GetWindowText` for title
  - `GetWindowThreadProcessId` + process name
  - `GetLastInputInfo` to compute `idle_seconds`
  - `GetAsyncKeyState` / low-cost counters for click/keypress counts within interval (no content)
- Batch POST to server `/api/v1/activity` (new endpoint).

## Server
- New table `activity_logs` (id, device_id, ts, window_title, process, idle_seconds, clicks, keys).
- API:
  - `POST /api/v1/activity` (agent -> server)
  - `GET /api/v1/activity` with filters (device_id, date range, search, paging).

## Portal
- New left-nav tab “Activity”.
- Views:
  - Timeline/stream table with search & filters.
  - Per-device summary (active time %, top apps, idle vs active).

## Privacy / Storage
- No keystroke content; titles only.
- Configurable retention (e.g., 30 days) – add server setting later.

## Open Questions
- Sampling interval preference?
- Do we need screenshot capture? (not included here)
- Should click/key counts be per-sample or cumulative?

## Next Steps
1) Implement agent sampler + batch post.
2) Add server model/API + migrations.
3) Build portal “Activity” tab consuming the new API.
4) Wire retention/limits and basic charts.
