"""
event_logs.py — Windows Event Log collection using PowerShell Get-WinEvent.
"""

import json
import os
import subprocess
import time

from config import LOG_COLLECT_INTERVAL, CREATE_NO_WINDOW
from logger import log
from network import api_call, powershell_available

# ── Event filter configuration ────────────────────────────────────────────────

EVENT_STATE_FILE = "event_state.json"

EVENT_LOG_FILTERS: dict = {
    'Security': [
        4624, 4625, 4634, 4647, 4648, 4675,
        4768, 4769, 4770, 4771, 4776,
        4672, 4673, 4674, 4964,
        4688, 4689, 4696,
        4656, 4663, 4658, 4670,
        4720, 4722, 4723, 4724, 4725, 4726,
        4727, 4728, 4729, 4732, 4733, 4735, 4756, 4757,
        4778, 4779, 4800, 4801,
        4798, 4799,
        4719, 4739, 4902, 4907,
        4608, 4609, 4616, 1102,
        5379,
    ],
    'System': [1074, 1, 41, 6005, 6006, 6008, 6009, 7001, 7002, 10000, 10001, 10002, 10100],
    'Application': [1000, 1001, 1002, 11, 7, 51, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 24, 50],
}

EVENT_ID_NAMES: dict = {
    4624: 'login_success', 4625: 'login_failed', 4634: 'logoff',
    4647: 'user_logoff', 4648: 'logon_explicit_creds', 4675: 'sids_filtered',
    4768: 'kerberos_ticket_req', 4769: 'kerberos_service_req', 4770: 'kerberos_ticket_renew',
    4771: 'kerberos_preauth_failed', 4776: 'ntlm_auth',
    4672: 'special_privs_assigned', 4673: 'priv_service_call', 4674: 'priv_obj_access', 4964: 'special_groups_assigned',
    4688: 'process_creation', 4689: 'process_termination', 4696: 'process_token_assigned',
    4656: 'handle_requested', 4663: 'object_accessed', 4658: 'handle_closed', 4670: 'permissions_changed',
    4720: 'user_created', 4722: 'user_enabled', 4723: 'password_change_attempt',
    4724: 'password_reset_attempt', 4725: 'user_disabled', 4726: 'user_deleted',
    4727: 'security_group_created', 4728: 'member_added_global', 4729: 'member_removed_global',
    4732: 'member_added_local', 4733: 'member_removed_local', 4735: 'security_group_modified',
    4738: 'user_account_changed', 4756: 'member_added_global', 4757: 'member_removed_global',
    5379: 'user_account_management',
    4778: 'session_reconnected', 4779: 'session_disconnected', 4800: 'workstation_locked', 4801: 'workstation_unlocked',
    4798: 'user_group_enum', 4799: 'sec_group_enum',
    4719: 'audit_policy_changed', 4739: 'domain_policy_changed', 4902: 'per_user_audit_changed', 4907: 'obj_auditing_changed',
    4608: 'windows_starting', 4609: 'windows_shutting_down', 4616: 'system_time_changed', 1102: 'audit_log_cleared',
    5156: 'connection_allowed', 5157: 'connection_blocked',
    1074: 'system_shutdown_restart', 1: 'system_start', 41: 'kernel_power_error',
    6005: 'event_log_started', 6006: 'event_log_stopped', 6008: 'unexpected_shutdown',
    6009: 'system_version_info', 7001: 'service_start_success', 7002: 'service_start_failure',
    10000: 'wlan_connected', 10001: 'wlan_disconnected', 10002: 'wlan_error',
    10100: 'generic_system_error',
    1000: 'app_crash', 1001: 'error_reporting', 1002: 'app_hang', 11: 'disk_error',
    7: 'disk_controller_error', 51: 'disk_warning', 12: 'driver_init_failure',
}


# ── Collector class ───────────────────────────────────────────────────────────

class EventLogCollector:
    """Collects Windows Event Logs using PowerShell Get-WinEvent."""

    def __init__(self, server_url: str, device_id: str, hostname: str):
        self.server_url = server_url
        self.device_id = device_id
        self.hostname = hostname
        self.state = self._load_state()
        self.retry_batch: list = []

    def _state_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), EVENT_STATE_FILE)

    def _load_state(self) -> dict:
        try:
            with open(self._state_path(), 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            with open(self._state_path(), 'w') as f:
                json.dump(self.state, f)
        except Exception as e:
            log('WARN', f"Failed to save event state: {e}")

    def collect_and_send(self) -> None:
        """One full collection cycle: query logs, batch, POST to server."""
        all_events = list(self.retry_batch)
        self.retry_batch = []

        for log_source, event_ids in EVENT_LOG_FILTERS.items():
            try:
                events = self._query_log(log_source, event_ids)
                all_events.extend(events)
            except Exception as e:
                log('WARN', f"Failed to collect {log_source} logs: {e}")

        if not all_events:
            return

        log('INFO', f"📋 Collected {len(all_events)} event log(s), sending to server…")
        payload = {"device_id": self.device_id, "logs": all_events}
        resp = api_call(self.server_url, 'POST', '/api/v1/device/logs', payload)
        if resp and resp.get('status') == 'ok':
            log('INFO', f"✓ Sent {resp.get('inserted', 0)} event logs to server")
            self._save_state()
        else:
            log('WARN', f"Failed to send event logs, will retry ({len(all_events)} events)")
            self.retry_batch = all_events

    def _query_log(self, log_source: str, event_ids: list) -> list:
        """Use PowerShell Get-WinEvent to retrieve events since last timestamp."""
        if not powershell_available():
            log('WARN', f"Skipping {log_source} event collection: PowerShell unavailable.")
            return []

        last_ts = self.state.get(log_source, "")
        event_ids_set = set(event_ids)
        start_clause = f"; StartTime=(Get-Date '{last_ts}')" if last_ts else ""

        if log_source == "Security":
            ps_command = (
                f"Get-WinEvent -FilterHashtable @{{LogName='Security'{start_clause}}} -MaxEvents 200 -ErrorAction Stop | "
                f"ForEach-Object {{ @{{ Id=$_.Id; LogName=$_.LogName; "
                f"TimeCreated=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
                f"Message=$_.Message; "
                f"Username=$(if ($_.Properties.Count -gt 5) {{ $_.Properties[5].Value }} else {{ $_.UserId }}) "
                f"}} | ConvertTo-Json -Compress }}"
            )
            log('DEBUG', "Querying Security log (broad, filter in Python)…")
        else:
            ids_csv = ",".join(str(eid) for eid in event_ids)
            ps_command = (
                f"Get-WinEvent -FilterHashtable @{{LogName='{log_source}'; Id={ids_csv}{start_clause}}} -MaxEvents 100 -ErrorAction Stop | "
                f"ForEach-Object {{ @{{ Id=$_.Id; LogName=$_.LogName; "
                f"TimeCreated=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
                f"Message=$_.Message; Username=$_.UserId "
                f"}} | ConvertTo-Json -Compress }}"
            )

        try:
            result = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-NonInteractive', '-Command', ps_command],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                err = result.stderr.strip()
                if "No events were found" in err:
                    return []
                if "Access is denied" in err and log_source == "Security":
                    log('ERROR', "Permission denied: Cannot read Security log. Run agent as Administrator.")
                    return []
                log('ERROR', f"PowerShell {log_source} failed: {err[:300]}")
                raise Exception(err)

            stdout = result.stdout.strip()
            if not stdout:
                return []

            lines = stdout.split('\n')
            events: list = []
            newest_ts = last_ts

            for line in lines:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue

                eid = evt.get('Id')
                if log_source == "Security" and eid not in event_ids_set:
                    continue

                ts_str = evt.get('TimeCreated')
                raw_user = evt.get('Username')
                uname = str(raw_user) if raw_user is not None and str(raw_user).strip() != "" else None

                events.append({
                    "event_id": eid,
                    "event_name": EVENT_ID_NAMES.get(eid, f"event_{eid}"),
                    "log_source": log_source,
                    "timestamp": ts_str,
                    "username": uname,
                    "hostname": self.hostname,
                    "message": (str(evt.get('Message') or ''))[:500],
                })

                if not newest_ts or ts_str > newest_ts:
                    newest_ts = ts_str

            if newest_ts:
                self.state[log_source] = newest_ts

            if log_source == "Security":
                log('INFO', f"📋 Security: {len(events)} matching events out of {len(lines)} raw")

            return events

        except subprocess.TimeoutExpired:
            log('WARN', f"Get-WinEvent timed out for {log_source}")
            return []
        except Exception as e:
            log('WARN', f"Error querying {log_source}: {str(e)[:200]}")
            return []


# ── Background thread ─────────────────────────────────────────────────────────

def event_log_collector_thread(server_url: str, device_id: str, hostname: str) -> None:
    """Background thread: runs EventLogCollector on a timer."""
    collector = EventLogCollector(server_url, device_id, hostname)
    log('INFO', f"📋 Event Log Collector started (interval: {LOG_COLLECT_INTERVAL}s)")
    while True:
        try:
            collector.collect_and_send()
        except Exception as e:
            log('ERROR', f"Event log collection error: {e}")
        time.sleep(LOG_COLLECT_INTERVAL)
