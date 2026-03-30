"""
activity_db.py — Local SQLite-backed offline activity log for SentraGuard.

Storage path: C:\ProgramData\SentraGuard\activity_cache.db
Each event is stored locally and deleted after successful sync to the portal.
Schema is forward-migrated on startup to add new columns without data loss.
"""

import os
import sqlite3
import threading
from pathlib import Path

from logger import log

# Use ProgramData so the SYSTEM service account can always read/write.
# Fall back to a sibling path if ProgramData is unavailable.
_BASE_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SentraGuard"
try:
    _BASE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Will surface at connect time with a clear error

DB_PATH = _BASE_DIR / "activity_cache.db"
_lock = threading.Lock()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cursor.fetchall())


# ── Init & Migration ───────────────────────────────────────────────────────────

def init_db():
    """Create the activity_events table and run column migrations."""
    with _lock:
        try:
            conn = _get_connection()
            cur = conn.cursor()

            # Base table (always safe to run)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    event     TEXT    NOT NULL,
                    username  TEXT    NOT NULL DEFAULT '',
                    duration  TEXT    NOT NULL DEFAULT '0s'
                )
            """)

            # Forward migrations — add columns that may be missing in older DBs
            _new_cols = [
                ("machine",        "TEXT DEFAULT ''"),
                ("serial",         "TEXT DEFAULT ''"),
                ("ip_address",     "TEXT DEFAULT ''"),
                ("os_version",     "TEXT DEFAULT ''"),
                # Application / input tracking columns (APP_USAGE events)
                ("process_name",   "TEXT DEFAULT ''"),
                ("window_title",   "TEXT DEFAULT ''"),
                ("url",            "TEXT DEFAULT ''"),
                ("idle_seconds",   "INTEGER DEFAULT 0"),
                ("mouse_clicks",   "INTEGER DEFAULT 0"),
                ("keypress_count", "INTEGER DEFAULT 0"),
            ]
            for col, col_def in _new_cols:
                if not _column_exists(cur, "activity_events", col):
                    cur.execute(f"ALTER TABLE activity_events ADD COLUMN {col} {col_def}")
                    log("INFO", f"activity_db: migrated — added column '{col}'")

            conn.commit()
            conn.close()
            log("INFO", "activity_db: initialized OK")
        except Exception as e:
            log("ERROR", f"activity_db init failed: {e}")


# ── Write ──────────────────────────────────────────────────────────────────────

def insert_event(
    timestamp: str,
    event: str,
    username: str,
    duration: str = "0s",
    machine: str = "",
    serial: str = "",
    ip_address: str = "",
    os_version: str = "",
    process_name: str = "",
    window_title: str = "",
    url: str = "",
    idle_seconds: int = 0,
    mouse_clicks: int = 0,
    keypress_count: int = 0,
):
    """Insert a single activity event into the local cache."""
    with _lock:
        try:
            conn = _get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO activity_events
                   (timestamp, event, username, duration, machine, serial, ip_address, os_version,
                    process_name, window_title, url, idle_seconds, mouse_clicks, keypress_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, event, username, duration, machine, serial, ip_address, os_version,
                 process_name, window_title, url, idle_seconds, mouse_clicks, keypress_count),
            )
            conn.commit()
            conn.close()
            if event in ("STARTUP", "SHUTDOWN", "LOGIN", "LOGOUT"):
                log("INFO", f"activity_db: logged {event} for {username}@{machine}")
        except Exception as e:
            log("ERROR", f"activity_db insert failed: {e}")


# ── Read ───────────────────────────────────────────────────────────────────────

def get_unsynced(limit: int = 100) -> tuple[list, list]:
    """Return up to `limit` unsynchronised events as (events_list, ids_list)."""
    with _lock:
        try:
            conn = _get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM activity_events ORDER BY id ASC LIMIT ?", (limit,)
            )
            rows = cur.fetchall()
            conn.close()

            if not rows:
                return [], []

            ids = [row["id"] for row in rows]
            keys = lambda row: row.keys()
            events = [
                {
                    "timestamp":     row["timestamp"],
                    "event":         row["event"],
                    "username":      row["username"],
                    "duration":      row["duration"],
                    "machine":       row["machine"]    if "machine"    in keys(row) else "",
                    "serial":        row["serial"]     if "serial"     in keys(row) else "",
                    "ip_address":    row["ip_address"] if "ip_address" in keys(row) else "",
                    "os_version":    row["os_version"] if "os_version" in keys(row) else "",
                    "process_name":  row["process_name"]  if "process_name"  in keys(row) else "",
                    "window_title":  row["window_title"]  if "window_title"  in keys(row) else "",
                    "url":           row["url"]           if "url"           in keys(row) else "",
                    "idle_seconds":  row["idle_seconds"]  if "idle_seconds"  in keys(row) else 0,
                    "mouse_clicks":  row["mouse_clicks"]  if "mouse_clicks"  in keys(row) else 0,
                    "keypress_count":row["keypress_count"] if "keypress_count" in keys(row) else 0,
                }
                for row in rows
            ]
            return events, ids
        except Exception as e:
            log("ERROR", f"activity_db get_unsynced failed: {e}")
            return [], []


# ── Delete ─────────────────────────────────────────────────────────────────────

def delete_synced(ids: list):
    """Remove successfully synced event IDs from the local cache."""
    if not ids:
        return
    with _lock:
        try:
            conn = _get_connection()
            cur = conn.cursor()
            placeholders = ",".join("?" * len(ids))
            cur.execute(f"DELETE FROM activity_events WHERE id IN ({placeholders})", ids)
            conn.commit()
            conn.close()
        except Exception as e:
            log("ERROR", f"activity_db delete_synced failed: {e}")


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_pending_count() -> int:
    """Return the number of events pending sync."""
    with _lock:
        try:
            conn = _get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM activity_events")
            count = cur.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0
