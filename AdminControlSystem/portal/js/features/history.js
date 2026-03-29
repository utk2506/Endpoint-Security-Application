/**
 * features/history.js
 * Command history with pagination, sorting, filtering, and details modal.
 */

import { api } from '../core/api.js';
import { $, formatDate, escapeHtml, escapeAttr } from '../core/utils.js';
import { selectedDeviceId } from './devices.js';
import { refreshAdminList } from './adminList.js';

let currentHistoryPage = 1;
let historyLimit       = 20;
let sortColumn         = 'created_at';
let sortDirection      = 'desc';
let _historyCache      = [];

export function changeLimit() {
    const selector = $('limitSelect');
    if (selector) historyLimit = parseInt(selector.value, 10) || 20;
    currentHistoryPage = 1;
    loadHistory();
}

export function jumpToPage() {
    const input = $('pageJumpInput');
    if (input) {
        let desired = parseInt(input.value, 10);
        if (isNaN(desired) || desired < 1) desired = 1;
        currentHistoryPage = desired;
        loadHistory();
    }
}

export function sortBy(col) {
    if (sortColumn === col) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn    = col;
        sortDirection = 'asc';
    }
    loadHistory();
}

export function applyFilters() {
    currentHistoryPage = 1;
    loadHistory();
}

export function clearFilters() {
    if ($('filterDevice')) $('filterDevice').value = '';
    if ($('filterAction')) $('filterAction').value = '';
    if ($('filterStatus')) $('filterStatus').value = '';
    if ($('filterSearch')) $('filterSearch').value = '';
    currentHistoryPage = 1;
    loadHistory();
}

export function changePage(delta) {
    currentHistoryPage += delta;
    if (currentHistoryPage < 1) currentHistoryPage = 1;
    loadHistory();
}

export async function loadHistory() {
    try {
        let url = `/commands/history?limit=${historyLimit}&page=${currentHistoryPage}&sort_by=${encodeURIComponent(sortColumn)}&sort_dir=${encodeURIComponent(sortDirection)}`;

        const device = $('filterDevice')?.value;
        const action = $('filterAction')?.value;
        const status = $('filterStatus')?.value;
        const search = $('filterSearch')?.value;

        if (device) url += `&device_id=${encodeURIComponent(device)}`;
        if (action) url += `&action=${encodeURIComponent(action)}`;
        if (status) url += `&status=${encodeURIComponent(status)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const data    = await api('GET', url);
        const history = data.commands || [];

        // Auto-refresh admin list when relevant commands complete
        if (selectedDeviceId) {
            const completedRecently = history.filter(c =>
                c.device_id == selectedDeviceId &&
                c.status === 'completed' &&
                ['grant', 'revoke', 'check', 'create_user'].includes(c.action)
            );
            if (completedRecently.length > 0) {
                const latestId = Math.max(...completedRecently.map(c => c.id));
                if (window._lastAutoRefreshId !== latestId) {
                    window._lastAutoRefreshId = latestId;
                    console.log(`[Auto-Refresh] Command #${latestId} completed. Refreshing admin list...`);
                    refreshAdminList();
                }
            }
        }

        _historyCache = history;
        const total = data.total || 0;
        const page  = data.page  || 1;
        const limit = data.limit || 20;

        const tbody = $('historyTableBody');

        if (history.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No commands found</div>
            </td></tr>`;
            if ($('statCommands'))  $('statCommands').textContent  = '0';
            if ($('pageInfoText'))  $('pageInfoText').textContent  = '0 results';
            if ($('pageIndicator')) $('pageIndicator').textContent = '1';
            if ($('btnPrevPage'))   $('btnPrevPage').disabled = true;
            if ($('btnNextPage'))   $('btnNextPage').disabled = true;
            return;
        }

        const completedCount = history.filter(c => c.status === 'completed').length;
        if ($('statCommands')) $('statCommands').textContent = completedCount;

        const totalPages = Math.ceil(total / limit) || 1;
        if ($('pageInfoText')) {
            const startIdx = total === 0 ? 0 : ((page - 1) * limit) + 1;
            const endIdx   = Math.min(page * limit, total);
            $('pageInfoText').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }
        if ($('totalPagesSpan'))  $('totalPagesSpan').textContent = totalPages;
        if ($('pageJumpInput')) {
            $('pageJumpInput').max   = totalPages;
            $('pageJumpInput').value = page;
        }
        if ($('btnPrevPage')) $('btnPrevPage').disabled = (page <= 1);
        if ($('btnNextPage')) $('btnNextPage').disabled = (page >= totalPages);

        // Sort icons
        const columns = ['id', 'device_hostname', 'action', 'username', 'status', 'result', 'created_at'];
        for (const c of columns) {
            const el = $(`sort-idx-${c}`);
            if (el) {
                if (c === sortColumn) {
                    el.textContent  = sortDirection === 'asc' ? '▲' : '▼';
                    el.style.color  = 'var(--accent)';
                } else {
                    el.textContent = '';
                    el.style.color = '';
                }
            }
        }

        if (tbody) {
            tbody.innerHTML = history.map(c => {
                const actionIcons = { grant: '✅', revoke: '🚫', check: '🔍', shell: '💻', create_user: '👤', notify: '📢' };
                const statusClass = `badge-${c.status}`;

                let actionText = c.action;
                if (c.action === 'grant') {
                    if (c.expires_at) {
                        const diffMins = Math.round((new Date(c.expires_at) - new Date(c.created_at)) / 60000);
                        actionText = `grant (${diffMins}m)`;
                    } else {
                        actionText = 'grant (Permanent)';
                    }
                }

                let resultHtml = escapeHtml(c.result || '—');
                if (c.action === 'revoke' && c.payload === 'System Auto-Revoke') {
                    resultHtml = `<span class="badge badge-warning" style="font-size:10px;">⚡ SYSTEM AUTO-REVOKE</span>`;
                }

                let timeStr = c.created_at;
                if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
                const time = formatDate(timeStr);

                let expiryBadge  = '';
                let payloadBadge = '';

                if (c.action === 'grant' && c.expires_at) {
                    if (c.auto_revoked) {
                        expiryBadge = ` <span style="font-size:10px; background:rgba(34,197,94,0.15); color:#22c55e;
                            border:1px solid rgba(34,197,94,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                            ✅ Auto-Revoked</span>`;
                    } else {
                        const expMs = new Date(c.expires_at).getTime() - Date.now();
                        if (expMs > 0) {
                            const h = Math.floor(expMs / 3600000);
                            const m = Math.floor((expMs % 3600000) / 60000);
                            const countdown = h > 0 ? `${h}h ${m}m` : `${m}m`;
                            expiryBadge = ` <span style="font-size:10px; background:rgba(251,189,35,0.15); color:#fbbf24;
                                border:1px solid rgba(251,189,35,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                                ⏱ ${countdown}</span>`;
                        } else {
                            expiryBadge = ` <span style="font-size:10px; background:rgba(239,68,68,0.15); color:#ef4444;
                                border:1px solid rgba(239,68,68,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                                ⏱ Expiring…</span>`;
                        }
                    }
                }

                if (c.action === 'revoke' && c.payload === 'System Auto-Revoke') {
                    payloadBadge = `<span style="font-size:10px; background:rgba(34,197,94,0.15); color:#22c55e;
                            border:1px solid rgba(34,197,94,0.3); border-radius:4px; padding:1px 6px; margin-left:4px; display:inline-block; margin-top:4px;">
                            🤖 System Auto-Revoke</span>`;
                } else if (c.action === 'grant') {
                    if (c.expires_at) {
                        const durationMins = Math.round((new Date(c.expires_at) - new Date(c.created_at)) / 60000);
                        payloadBadge = `<span style="font-size:10px; background:rgba(59,130,246,0.15); color:#3b82f6;
                            border:1px solid rgba(59,130,246,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                            ${durationMins}m grant</span>`;
                    } else {
                        payloadBadge = `<span style="font-size:10px; background:rgba(59,130,246,0.15); color:#3b82f6;
                            border:1px solid rgba(59,130,246,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                            Permanent</span>`;
                    }
                } else if (c.action === 'create_user') {
                    payloadBadge = `<span style="font-size:10px; background:rgba(168,85,247,0.15); color:#a855f7;
                            border:1px solid rgba(168,85,247,0.3); border-radius:4px; padding:1px 6px; margin-left:4px;">
                            New User</span>`;
                }

                return `<tr>
                    <td style="font-weight:600; color:var(--text-primary)">#${c.id}</td>
                    <td>${escapeHtml(c.device_hostname)}</td>
                    <td onclick="openCmdDetailsModal(${c.id})" style="cursor:pointer;" title="Click for details">
                        <span style="display:flex; align-items:center;">${actionIcons[c.action] || '⚙️'} <span style="text-transform:capitalize; margin-left:4px;">${actionText}</span></span>
                        <div style="margin-top:2px;">${payloadBadge}${expiryBadge}</div>
                    </td>
                    <td>${c.username ? escapeHtml(c.username) : '—'}</td>
                    <td><span class="badge ${statusClass}"><span class="badge-dot"></span>${c.status}</span></td>
                    <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer;"
                        onclick="openCmdDetailsModal(${c.id})"
                        title="${c.result ? escapeAttr(c.result) : 'Click for details'}">${resultHtml}</td>
                    <td style="color:var(--text-muted); font-size:12px;">${time}</td>
                </tr>`;
            }).join('');
        }
    } catch {
        // silent
    }
}

export function openCmdDetailsModal(cmdId) {
    const cmd = _historyCache.find(c => c.id === cmdId);
    if (!cmd) return;

    if ($('cmdModalId'))      $('cmdModalId').textContent      = `#${cmd.id}`;
    if ($('cmdModalDevice'))  $('cmdModalDevice').textContent   = `${cmd.device_hostname || 'Unknown'} (${cmd.device_id})`;
    if ($('cmdModalAction'))  $('cmdModalAction').textContent   = cmd.action.replace('_', ' ');
    if ($('cmdModalTarget'))  $('cmdModalTarget').textContent   = cmd.username || '—';
    if ($('cmdModalTime'))    $('cmdModalTime').textContent     = formatDate(cmd.created_at);
    if ($('cmdModalPayload')) $('cmdModalPayload').textContent  = cmd.payload || 'None';
    if ($('cmdModalResult'))  $('cmdModalResult').textContent   = cmd.result  || 'No result yet';

    $('cmdDetailsModal').classList.add('show');
}

export function closeCmdDetailsModal(event) {
    if (event && event.target !== event.currentTarget) return;
    $('cmdDetailsModal').classList.remove('show');
}
