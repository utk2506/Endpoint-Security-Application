/**
 * Admin Control System — Dashboard Logic
 * Handles all API communication, UI updates, and polling.
 */

const API_BASE = window.location.origin;
let selectedDeviceId = null;
let pollInterval = null;

// ── Helpers ────────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }
    return res.json();
}

function $(id) { return document.getElementById(id); }

function showResult(type, icon, text) {
    const box = $('resultBox');
    box.className = `result-box show ${type}`;
    $('resultIcon').textContent = icon;
    $('resultText').textContent = text;
}

function hideResult() {
    $('resultBox').className = 'result-box';
}

// ── Toast Notifications ────────────────────────────────────────────────────

function toast(message, type = 'info') {
    const container = $('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
    container.appendChild(el);
    setTimeout(() => {
        el.classList.add('toast-exit');
        setTimeout(() => el.remove(), 300);
    }, 3500);
}

// ── Connection Status ──────────────────────────────────────────────────────

function setConnected(online) {
    const dot = $('connectionDot');
    const text = $('connectionText');
    if (online) {
        dot.classList.remove('offline');
        text.textContent = 'Connected to server';
    } else {
        dot.classList.add('offline');
        text.textContent = 'Server unreachable';
    }
}

// ── Load Devices ───────────────────────────────────────────────────────────

async function loadDevices() {
    try {
        const devices = await api('GET', '/devices');
        setConnected(true);

        const select = $('deviceSelect');
        const currentVal = select.value;
        select.innerHTML = '<option value="">— Select a device —</option>';

        devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.hostname}  (${d.ip_address})`;
            select.appendChild(opt);
        });

        // Restore selection
        if (currentVal) select.value = currentVal;

        $('statDevices').textContent = devices.length;
    } catch {
        setConnected(false);
    }
}

// ── Device selection ───────────────────────────────────────────────────────

$('deviceSelect')?.addEventListener('change', function () {
    selectedDeviceId = this.value ? parseInt(this.value) : null;
    hideResult();
    if (selectedDeviceId) {
        refreshAdminList();
    }
});

// ── Actions ────────────────────────────────────────────────────────────────

async function checkStatus() {
    if (!selectedDeviceId) {
        toast('Please select a device first', 'error');
        return;
    }
    try {
        showResult('info', '🔄', 'Sending check command to agent…');
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'check',
        });
        toast('Check command sent — waiting for agent response', 'info');
        loadHistory();
        // Refresh admin list after a delay to give agent time
        setTimeout(refreshAdminList, 6000);
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

async function grantAdmin() {
    const username = $('usernameInput').value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Enter a username', 'error'); return; }

    try {
        showResult('info', '🔄', `Granting admin to "${username}"…`);
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'grant',
            username,
        });
        toast(`Grant command queued for "${username}"`, 'success');
        showResult('success', '✅', `Grant command queued for "${username}"`);
        loadHistory();
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

async function revokeAdmin() {
    const username = $('usernameInput').value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Enter a username', 'error'); return; }

    try {
        showResult('info', '🔄', `Revoking admin from "${username}"…`);
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'revoke',
            username,
        });
        toast(`Revoke command queued for "${username}"`, 'success');
        showResult('success', '✅', `Revoke command queued for "${username}"`);
        loadHistory();
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

// ── Admin List ─────────────────────────────────────────────────────────────

async function refreshAdminList() {
    if (!selectedDeviceId) return;

    try {
        const data = await api('GET', `/admin_list/${selectedDeviceId}`);
        const tbody = $('adminTableBody');

        if (!data.admin_users || data.admin_users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3">
                <div class="empty-state">
                    <span class="icon">📋</span>
                    No admin data yet — click Check Status
                </div>
            </td></tr>`;
            $('statAdmins').textContent = '0';
            return;
        }

        $('statAdmins').textContent = data.admin_users.length;

        tbody.innerHTML = data.admin_users.map(user => {
            const safeUser = escapeAttr(user.replace(/\\/g, '\\\\'));
            return `
            <tr>
                <td style="font-weight:600; color:var(--text-primary)">${escapeHtml(user)}</td>
                <td><span class="badge badge-admin"><span class="badge-dot"></span>Admin</span></td>
                <td>
                    <button class="btn btn-danger" style="padding:6px 14px; font-size:12px;"
                        onclick="quickRevoke('${safeUser}')">
                        🚫 Revoke
                    </button>
                </td>
            </tr>
        `}).join('');
    } catch (e) {
        console.error('Failed to load admin list:', e);
    }
}

function quickRevoke(username) {
    $('usernameInput').value = username;
    revokeAdmin();
}

// ── Command History ────────────────────────────────────────────────────────

async function loadHistory() {
    try {
        const history = await api('GET', '/commands/history?limit=25');
        const tbody = $('historyTableBody');

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No commands yet</div>
            </td></tr>`;
            $('statCommands').textContent = '0';
            return;
        }

        const completedCount = history.filter(c => c.status === 'completed').length;
        $('statCommands').textContent = completedCount;

        tbody.innerHTML = history.map(c => {
            const actionIcons = { grant: '✅', revoke: '🚫', check: '🔍' };
            const statusClass = `badge-${c.status}`;
            let timeStr = c.created_at;
            if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
            const time = timeStr ? new Date(timeStr).toLocaleString() : '—';

            return `<tr>
                <td style="font-weight:600; color:var(--text-primary)">#${c.id}</td>
                <td>${escapeHtml(c.device_hostname)}</td>
                <td>${actionIcons[c.action] || ''} ${c.action}</td>
                <td>${c.username ? escapeHtml(c.username) : '—'}</td>
                <td><span class="badge ${statusClass}"><span class="badge-dot"></span>${c.status}</span></td>
                <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                    title="${c.result ? escapeAttr(c.result) : ''}">${c.result ? escapeHtml(c.result) : '—'}</td>
                <td style="color:var(--text-muted); font-size:12px;">${time}</td>
            </tr>`;
        }).join('');
    } catch {
        // silent
    }
}

// ── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// ── Polling ────────────────────────────────────────────────────────────────

async function pollAll() {
    await loadDevices();
    await loadHistory();
    if (selectedDeviceId) await refreshAdminList();
}

// Initial load
pollAll();

// Auto-refresh every 5 seconds
pollInterval = setInterval(pollAll, 5000);
