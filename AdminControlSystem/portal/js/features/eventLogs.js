/**
 * features/eventLogs.js
 * Event log listing with pagination, sorting, filtering, summary stats, and details modal.
 */

import { api } from '../core/api.js';
import { $, formatDate, escapeHtml, escapeAttr } from '../core/utils.js';

let evtCurrentPage  = 1;
let evtLimit        = 20;
let evtSortColumn   = 'timestamp';
let evtSortDirection= 'desc';

const EVENT_NAME_LABELS = {
    login_success: '🟢 Login Success', login_failed: '🔴 Login Failed',
    logoff: '🔵 Logoff', user_logoff: '🔵 User Logoff',
    logon_explicit_creds: '🔑 Explicit Creds', special_privs_assigned: '⚡ Special Privs',
    session_reconnect: '🔄 Session Reconnect', session_disconnect: '🔌 Session Disconnect',
    workstation_locked: '🔒 Workstation Locked', workstation_unlocked: '🔓 Workstation Unlocked',
    account_created: '👤 Account Created', account_enabled: '✅ Account Enabled',
    password_change: '🔑 Password Change', password_reset: '🔑 Password Reset',
    account_disabled: '🚫 Account Disabled', account_deleted: '❌ Account Deleted',
    user_added_to_group: '➕ Added to Group', user_removed_from_group: '➖ Removed from Group',
    account_changed: '✏️ Account Changed', user_added_to_priv_group: '⚡ Added to Priv Group',
    user_removed_from_priv_group: '⚡ Removed from Priv Group',
    process_created: '▶️ Process Created', process_terminated: '⏹️ Process Terminated',
    priv_use: '🛡️ Privilege Used', priv_service_op: '🛡️ Privilege Service Op',
    system_startup: '🟢 System Startup', system_shutdown: '🔴 System Shutdown',
    unexpected_shutdown: '💥 Unexpected Shutdown', restart_initiated: '🔄 Restart',
    unexpected_shutdown_reason: '💥 Shutdown Reason',
    app_crash: '💥 App Crash', error_reporting: '📝 Error Report', app_hang: '⏸️ App Hang',
    driver_init_failure: '⚠️ Driver Failure', disk_controller_error: '💽 Disk Error',
    disk_error: '💽 Disk Error', disk_warning: '💽 Disk Warning',
    network_allowed: '🌐 Network Allowed', network_blocked: '🚫 Network Blocked',
};

export function applyEventFilters() {
    evtCurrentPage = 1;
    loadEventLogs();
}

export function clearEventFilters() {
    if ($('evtFilterDevice'))  $('evtFilterDevice').value  = '';
    if ($('evtFilterSource'))  $('evtFilterSource').value  = '';
    if ($('evtFilterEventId')) $('evtFilterEventId').value = '';
    if ($('evtFilterSearch'))  $('evtFilterSearch').value  = '';
    evtCurrentPage = 1;
    loadEventLogs();
}

export function changeEventPage(delta) {
    evtCurrentPage += delta;
    if (evtCurrentPage < 1) evtCurrentPage = 1;
    loadEventLogs();
}

export function changeEventLimit() {
    const sel = $('evtLimitSelect');
    if (sel) evtLimit = parseInt(sel.value, 10) || 20;
    evtCurrentPage = 1;
    loadEventLogs();
}

export function jumpToEventPage() {
    const input = $('evtPageJumpInput');
    if (input) {
        let desired = parseInt(input.value, 10);
        if (isNaN(desired) || desired < 1) desired = 1;
        evtCurrentPage = desired;
        loadEventLogs();
    }
}

export function sortEventsBy(col) {
    if (evtSortColumn === col) {
        evtSortDirection = evtSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        evtSortColumn    = col;
        evtSortDirection = 'asc';
    }
    loadEventLogs();
}

export async function loadEventLogs() {
    try {
        let url = `/api/v1/event-logs?limit=${evtLimit}&page=${evtCurrentPage}&sort_by=${encodeURIComponent(evtSortColumn)}&sort_dir=${encodeURIComponent(evtSortDirection)}`;

        const device  = $('evtFilterDevice')?.value;
        const source  = $('evtFilterSource')?.value;
        const eventId = $('evtFilterEventId')?.value;
        const search  = $('evtFilterSearch')?.value;

        if (device)  url += `&device_id=${encodeURIComponent(device)}`;
        if (source)  url += `&log_source=${encodeURIComponent(source)}`;
        if (eventId) url += `&event_id=${encodeURIComponent(eventId)}`;
        if (search)  url += `&search=${encodeURIComponent(search)}`;

        const data  = await api('GET', url);
        const logs  = data.logs  || [];
        const total = data.total || 0;
        const page  = data.page  || 1;
        const limit = data.limit || 20;

        const tbody = $('eventLogTableBody');

        if (logs.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No event logs found</div>
            </td></tr>`;
            if ($('evtPageInfoText'))   $('evtPageInfoText').textContent   = '0 results';
            if ($('evtTotalPagesSpan')) $('evtTotalPagesSpan').textContent = '1';
            if ($('evtPageJumpInput'))  $('evtPageJumpInput').value        = 1;
            if ($('btnEvtPrevPage'))    $('btnEvtPrevPage').disabled = true;
            if ($('btnEvtNextPage'))    $('btnEvtNextPage').disabled = true;
            return;
        }

        const totalPages = Math.ceil(total / limit) || 1;
        if ($('evtPageInfoText')) {
            const startIdx = total === 0 ? 0 : ((page - 1) * limit) + 1;
            const endIdx   = Math.min(page * limit, total);
            $('evtPageInfoText').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }
        if ($('evtTotalPagesSpan')) $('evtTotalPagesSpan').textContent = totalPages;
        if ($('evtPageJumpInput')) {
            $('evtPageJumpInput').max   = totalPages;
            $('evtPageJumpInput').value = page;
        }
        if ($('btnEvtPrevPage')) $('btnEvtPrevPage').disabled = (page <= 1);
        if ($('btnEvtNextPage')) $('btnEvtNextPage').disabled = (page >= totalPages);

        // Sort icons
        const evtColumns = ['timestamp', 'hostname', 'username', 'event_id', 'event_name', 'log_source'];
        for (const c of evtColumns) {
            const el = $(`evt-sort-${c}`);
            if (el) {
                if (c === evtSortColumn) {
                    el.textContent = evtSortDirection === 'asc' ? '▲' : '▼';
                    el.style.color = 'var(--accent)';
                } else {
                    el.textContent = '';
                    el.style.color = '';
                }
            }
        }

        if (tbody) {
            tbody.innerHTML = logs.map(evt => {
                let timeStr = evt.timestamp;
                if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
                const time  = formatDate(timeStr);
                const label = EVENT_NAME_LABELS[evt.event_name] || evt.event_name;

                const sourceBadgeColors = {
                    Security: 'var(--danger)', System: 'var(--warning)', Application: 'var(--accent)'
                };
                const sourceColor = sourceBadgeColors[evt.log_source] || 'var(--text-secondary)';

                return `<tr>
                    <td style="color:var(--text-muted); font-size:12px; white-space:nowrap;">${time}</td>
                    <td>${escapeHtml(evt.hostname || '—')}</td>
                    <td>${evt.username ? escapeHtml(evt.username) : '—'}</td>
                    <td style="font-weight:600; color:var(--text-primary);">${evt.event_id}</td>
                    <td style="font-size:12px;">${label}</td>
                    <td><span style="color:${sourceColor}; font-weight:500;">${evt.log_source}</span></td>
                    <td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer;"
                        onclick="openLogDetailsModal(${escapeAttr(JSON.stringify(evt))})"
                        title="Click to view full details">${evt.message ? escapeHtml(evt.message) : '—'}</td>
                </tr>`;
            }).join('');
        }
    } catch {
        // silent
    }
}

export async function loadEventLogSummary() {
    try {
        const data = await api('GET', '/api/v1/event-logs/summary');
        if ($('statTotalEvents'))    $('statTotalEvents').textContent    = data.total_events     || 0;
        if ($('statLogins'))         $('statLogins').textContent         = data.logins           || 0;
        if ($('statLogoffs'))        $('statLogoffs').textContent        = data.logoffs          || 0;
        if ($('statCrashes'))        $('statCrashes').textContent        = data.crashes          || 0;
        if ($('statPrivilegeEvents'))$('statPrivilegeEvents').textContent= data.privilege_events || 0;
    } catch {
        // silent
    }
}

export function openLogDetailsModal(evt) {
    if (!evt) return;

    if ($('logModalEventId')) $('logModalEventId').textContent = evt.event_id || '—';
    if ($('logModalSource')) {
        $('logModalSource').textContent = evt.log_source || '—';
        const sourceBadgeColors = { Security: 'var(--danger)', System: 'var(--warning)', Application: 'var(--accent)' };
        $('logModalSource').style.color = sourceBadgeColors[evt.log_source] || 'var(--text-secondary)';
    }

    let timeStr = evt.timestamp;
    if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
    if ($('logModalTime'))   $('logModalTime').textContent   = formatDate(timeStr);
    if ($('logModalDevice')) $('logModalDevice').textContent = evt.hostname  || '—';
    if ($('logModalUser'))   $('logModalUser').textContent   = evt.username  || '—';
    if ($('logModalMessage'))$('logModalMessage').textContent= evt.message   || 'No additional details provided.';

    const modal = $('logDetailsModal');
    if (modal) modal.classList.add('show');
}

export function closeLogDetailsModal() {
    const modal = $('logDetailsModal');
    if (modal) modal.classList.remove('show');
}
