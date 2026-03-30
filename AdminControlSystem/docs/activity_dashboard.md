# Activity Monitoring Dashboard — Technical Reference

## 1. Overview

The Activity tab in the SentraGuard portal displays a comprehensive real-time view of endpoint user activity events (LOGIN, LOGOUT, LOCK, UNLOCK, IDLE, ACTIVE, STARTUP, SHUTDOWN, SCREEN_ON, SCREEN_OFF). All data flows from endpoints → local log → sync service → server → portal.

---

## 2. Architecture: Two Activity Service Files

There are **two distinct** activity service files — do not confuse them:

| File | Side | Purpose |
|---|---|---|
| `server/activity_service.py` | **Server** | FastAPI APIRouter (`/api/activity/*`) — serves the portal |
| `agent/activityservice.py` | **Agent (endpoint)** | PyInstaller entry point for `activityservice.exe` Windows service |

### Data Flow

```
Windows Events / Idle Detection
        ↓
agent/activity_tracker.py   (SentraGuardActivitySvc — runs as SYSTEM)
        ↓
C:\ProgramData\SentraGuard\activity_cache.db   (local SQLite cache)
        ↓
agent/syncservice.py        (SentraGuardSyncSvc — uploads every 1-5 min)
        ↓  POST /api/activity/upload
server/activity_service.py  (stores in server database.db)
        ↓
Portal → GET /api/activity/analytics
        ↓
Activity Dashboard (KPIs, charts, heatmap, timeline, table)
```

---

## 3. Server API Endpoints

All endpoints are under prefix `/api/activity` (registered via `activity_router`).

### `POST /upload`
**Called by:** `SentraGuardSyncSvc` on each endpoint.

Accepts a batch of activity events. Deduplicates before storing.

**Payload:**
```json
{
  "device": "LAPTOP01",
  "serial": "SN-ABC123",
  "events": [
    {
      "timestamp": "2026-03-29T09:12:11",
      "event": "LOGIN",
      "username": "jsmith",
      "machine": "LAPTOP01",
      "serial": "SN-ABC123",
      "ip_address": "192.168.1.45",
      "duration": null,
      "os_version": "Windows 10 Pro"
    }
  ]
}
```

---

### `GET /events`
**Called by:** Portal event feed table.

Returns paginated, filtered activity events. Supports `?format=csv` or `?format=xlsx` for direct download.

**Query params:**
| Param | Type | Description |
|---|---|---|
| `machine` | string | Filter by machine hostname |
| `username` | string | Filter by username |
| `event` | string | Filter by event type (LOGIN, LOGOUT, etc.) |
| `synced` | string | `synced` or `pending` |
| `date_from` | ISO string | Start of date range |
| `date_to` | ISO string | End of date range |
| `search` | string | Free-text search across username, machine, serial, IP |
| `page` | int | Page number (default: 1) |
| `limit` | int | Page size (default: 50, max: 10000) |
| `format` | string | `csv` or `xlsx` to download file |

**Response:**
```json
{
  "total": 1247,
  "page": 1,
  "limit": 20,
  "pages": 63,
  "events": [
    {
      "id": 1,
      "device_id": "...",
      "timestamp": "2026-03-29T09:12:11Z",
      "event": "LOGIN",
      "username": "jsmith",
      "machine": "LAPTOP01",
      "serial": "SN-ABC123",
      "ip_address": "192.168.1.45",
      "duration": "—",
      "os_version": "Windows 10 Pro",
      "synced": true
    }
  ]
}
```

---

### `GET /kpi`
**Called by:** `loadActivityKpis()` — lightweight KPI refresh.

Returns live KPI counts based on each machine's most recent event.

**Query params:** `window_minutes` (default: 30) — look-back window for "active" classification.

**Response:**
```json
{
  "active": 28,
  "idle": 11,
  "locked": 5,
  "offline": 3,
  "total_events": 1247,
  "pending_count": 3,
  "total_registered": 47
}
```

---

### `GET /analytics`
**Called by:** `loadAnalyticsCharts()` — main dashboard data source.

Single endpoint that powers all dashboard visualizations. Accepts the same filter params as `/events` plus `date_from`/`date_to` for period control. Auto-adjusts time bucket granularity (hour/day/month) based on the selected range.

**Response structure:**
```json
{
  "range": { "from": "2026-03-29T00:00:00Z", "to": "2026-03-29T23:59:59Z" },

  "kpis": {
    "active": 28, "idle": 11, "locked": 5, "offline": 3,
    "total_events": 847, "pending_count": 2, "sync_health": 99
  },

  "hourly_series": {
    "bucket": "hour",
    "labels": ["00:00", "01:00", ...],
    "active":  [0, 0, 0, 2, 5, 18, 28, ...],
    "idle":    [0, 0, 0, 1, 2,  5, 11, ...],
    "locked":  [0, 0, 0, 0, 1,  2,  5, ...],
    "offline": [3, 3, 3, 3, 3,  3,  3, ...]
  },

  "top_machines": [
    { "machine": "WS-DEV02", "active_minutes": 444.0, "active_label": "7h 24m", "total_events": 120 }
  ],

  "session_stats": {
    "avg_minutes": 342.0, "avg_label": "5h 42m",
    "longest_minutes": 678.0, "longest_label": "11h 18m",
    "total_sessions": 63,
    "buckets": [
      { "label": "<1h", "count": 3 },
      { "label": "1-2h", "count": 8 },
      { "label": "2-4h", "count": 15 },
      { "label": "4-6h", "count": 22 },
      { "label": "6-8h", "count": 12 },
      { "label": "8-10h", "count": 2 },
      { "label": ">10h", "count": 1 }
    ]
  },

  "heatmap": {
    "hours": ["00", "01", ..., "23"],
    "rows": [
      { "machine": "WS-DEV02", "counts": [0, 0, 0, 0, 0, 0, 0, 1, 8, 15, 18, 12, 3, 14, 19, 20, 18, 12, 8, 4, 2, 1, 0, 0] }
    ]
  },

  "timeline": {
    "range_start": "2026-03-29T00:00:00Z",
    "range_end":   "2026-03-29T23:59:59Z",
    "ticks": [
      { "label": "00", "offset": 0 },
      { "label": "08", "offset": 33.3 },
      { "label": "16", "offset": 66.6 },
      { "label": "23", "offset": 100 }
    ],
    "users": [
      {
        "username": "jsmith",
        "segments": [
          { "state": "active", "start": "2026-03-29T09:12:00Z", "end": "2026-03-29T12:00:00Z" },
          { "state": "locked", "start": "2026-03-29T12:00:00Z", "end": "2026-03-29T13:05:00Z" },
          { "state": "active", "start": "2026-03-29T13:05:00Z", "end": "2026-03-29T15:11:00Z" }
        ]
      }
    ]
  }
}
```

---

### `GET /machines`
Returns distinct machine hostnames for the filter dropdown.
```json
{ "machines": ["DESKTOP04", "HR-DESK03", "LAPTOP01", "WS-DEV02"] }
```

### `GET /users`
Returns distinct usernames for the filter dropdown.
```json
{ "users": ["agarwal", "jsmith", "mlee", "pkumar", "rsingh"] }
```

### `PUT /events/{id}` / `DELETE /events/{id}`
Edit or delete a single event record. Requires admin role.

---

## 4. Event Types

| Event | Meaning | State |
|---|---|---|
| `LOGIN` | User logged into Windows | active |
| `LOGOUT` | User logged out | offline |
| `LOCK` | Machine screen locked | locked |
| `UNLOCK` | Machine screen unlocked | active |
| `IDLE` | No keyboard/mouse input for threshold period | idle |
| `ACTIVE` | Keyboard/mouse input resumed | active |
| `SCREEN_OFF` | Monitor powered off (WM_POWERBROADCAST) | locked |
| `SCREEN_ON` | Monitor powered on | active |
| `STARTUP` | System booted | active |
| `SHUTDOWN` | System shutting down | offline |

Detection methods:
- **Login/Logout:** Windows Security Event Log — Event IDs 4624 (login), 4647 (logout)
- **Lock/Unlock:** Event IDs 4800 (lock), 4801 (unlock)
- **Idle:** `GetLastInputInfo()` Win32 API — threshold configurable in `activity_tracker.py`
- **Screen:** `WM_POWERBROADCAST` messages

---

## 5. Portal JavaScript Module

**File:** `portal/js/features/activity.js`

### Key Exported Functions

| Function | Called by | What it does |
|---|---|---|
| `loadAnalyticsCharts()` | `dashboard.js` polling | Calls `/api/activity/analytics`, renders all charts |
| `loadActivity(page)` | `dashboard.js` polling | Loads event feed table + triggers analytics refresh |
| `loadActivityFilters()` | `dashboard.js` bootstrap | Populates Machine/User filter dropdowns |
| `loadActivityKpis()` | `dashboard.js` polling | Lightweight KPI refresh from `/api/activity/kpi` |
| `applyActivityFilters()` | HTML `onchange` attrs | Re-runs analytics + table with current filters |
| `resetActivityFilters()` | Reset button | Clears all filters, resets period to Today |
| `setActivityPeriod(period, el)` | Period tab `onclick` | Sets date range, refreshes dashboard |
| `applyActivityCustomRange()` | Custom range Apply btn | Reads custom date inputs, refreshes |
| `exportActivityCSV()` | Export CSV button | Downloads `/api/activity/events?format=csv` |
| `exportActivityXLSX()` | Export XLSX button | Downloads `/api/activity/events?format=xlsx` |
| `activityPrevPage()` / `activityNextPage()` | Pagination buttons | Navigates event table pages |

### Period → Date Range Mapping

| Period Tab | `date_from` | `date_to` |
|---|---|---|
| Today | Today 00:00 | Today 23:59 |
| Week | 6 days ago 00:00 | Today 23:59 |
| Month | 29 days ago 00:00 | Today 23:59 |
| Year | 364 days ago 00:00 | Today 23:59 |
| Custom | User-selected date input | User-selected date input |

### Internal State

```
_period       — active period tab: 'daily' | 'weekly' | 'monthly' | 'yearly' | 'custom'
_customFrom   — custom date-from value (YYYY-MM-DD string)
_customTo     — custom date-to value
_evtPage      — current event table page
_evtTotalPages — total pages from last /events response
_charts       — { 'actLineChart': Chart, 'actDonutChart': Chart }
_refreshing   — boolean guard preventing concurrent analytics fetches
```

---

## 6. Dashboard Components

### KPI Cards (`actKpiActive`, `actKpiIdle`, `actKpiLocked`, `actKpiOffline`, `actKpiTotal`, `actKpiHealth`)
Six cards showing current state counts and sync health percentage.

### Active Users Over Time — Line Chart (`actLineChart`)
Chart.js line chart. Plots active / idle / locked / offline machine counts over time. Bucket granularity auto-adjusts:
- ≤2 days → hourly buckets
- ≤120 days → daily buckets
- >120 days → monthly buckets

### Activity Breakdown — Donut Chart (`actDonutChart`)
Chart.js doughnut. Shows active/idle/locked/offline machine ratio with center count and inline legend.

### Top Active Machines — Bar Chart (`actTopMachinesBar`)
Pure HTML/CSS horizontal bars (no Chart.js). Ranks up to 7 machines by total active minutes in the period.

### Session Duration Analysis (`actSessionBuckets`)
Pure HTML/CSS vertical bar chart. Buckets: `<1h`, `1-2h`, `2-4h`, `4-6h`, `6-8h`, `8-10h`, `>10h`. Shows avg, longest session, and total count.

### Machine Usage Heatmap (`actHeatmapGrid`)
Grid of 24 hourly cells per machine row. Cell color intensity scales with event count. Blue gradient (`rgba(30,144,255, intensity)`).

### User Activity Timeline (`actTimelineRows`)
Gantt-style per-user timeline. Segments are colored by state:
- Green = active
- Yellow = idle
- Orange = locked

### Event Feed Table (`actEventTableBody`)
Paginated table from `/api/activity/events`. Columns: Timestamp, User, Machine, Serial, Event (colored badge), Duration, IP Address, Sync status.

---

## 7. HTML Element IDs

### Filter Controls
| ID | Element | Purpose |
|---|---|---|
| `actMachine` | `<select>` | Machine filter |
| `actUser` | `<select>` | User filter |
| `actEventType` | `<select>` | Event type filter |
| `actSynced` | `<select>` | Sync state filter |
| `actSearch` | `<input>` | Free-text search |
| `actDateFrom` / `actDateTo` | `<input type="date">` | Custom range inputs |
| `actCustomRange` | `<div>` | Custom range panel (shown/hidden) |

### KPI Values
`actKpiActive`, `actKpiIdle`, `actKpiLocked`, `actKpiOffline`, `actKpiTotal`, `actKpiHealth`

### Charts
`actLineChart` (canvas), `actDonutChart` (canvas), `actDonutCenter` (center label div)

### Donut Legend
`actDonutActive`, `actDonutIdle`, `actDonutLocked`, `actDonutOffline` — each contains `.act-donut-val` and `.act-donut-pct` spans

### Visualizations
`actTopMachinesBar`, `actSessionBuckets`, `actHeatmapGrid`, `actTimelineRows`, `actTimelineTicks`

### Session Stats
`actSessAvg`, `actSessLongest`, `actSessTotal`

### Event Table
`actEventTableBody`, `actEvtPageInfo`, `actEvtPrev`, `actEvtNext`

### Page Header
`actRangeLabel` — shows the active date range

---

## 8. CSS Classes (styles.css)

| Class | Purpose |
|---|---|
| `.act-kpi-grid` | 6-column responsive KPI grid |
| `.act-kpi-card` | Individual KPI card with colored top border via `--kpi-color` CSS var |
| `.act-period-tabs` / `.act-period-tab` | Period selector tab bar |
| `.act-filter-select` | Consistent filter dropdown/input styling |
| `.act-donut-legend-item` | Row in the donut chart legend |
| `.act-bar-row` / `.act-bar-track` / `.act-bar-fill` / `.act-bar-val` | Horizontal bar chart row |
| `.act-session-bars` / `.act-session-bar-wrap` / `.act-session-bar` | Session duration vertical bars |
| `.act-heatmap-hours` / `.act-heatmap-row` / `.act-heatmap-cell` | Heatmap grid layout |
| `.act-tl-user` / `.act-tl-track` / `.act-tl-block` / `.act-tl-tick` | Timeline Gantt rows |
| `.machine-tag` | Small badge for machine name in table |

---

## 9. Local Offline Storage (Agent Side)

When the endpoint cannot reach the server:

1. `activity_tracker.py` writes events to `C:\ProgramData\SentraGuard\activity_cache.db`
2. Each record stored with `synced = False`
3. Data survives reboots
4. `syncservice.py` polls every 1–5 minutes, checks connectivity, uploads unsynced records via `POST /api/activity/upload`
5. After successful upload, records are marked `synced = True`

Log rotation: if `activity_cache.db` exceeds 10MB, older records are archived.

---

## 10. Registering the Router in app.py

The `activity_router` must be included in `server/app.py`:

```python
from activity_service import activity_router
app.include_router(activity_router)
```

This registers all `/api/activity/*` endpoints.
