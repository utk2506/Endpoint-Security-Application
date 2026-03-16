/**
 * Admin Control System — Dashboard Logic
 * Handles all API communication, UI updates, and polling.
 */

const API_BASE = window.location.origin;
const WS_BASE = window.location.origin.replace('http', 'ws');
let selectedDeviceId = null;
let pollInterval = null;
let _deviceCache = [];  // cache of all devices with their all_users payload

// Terminal State
let term = null;
let terminalSocket = null;

// ── Helpers ────────────────────────────────────────────────────────────────

// ── Authentication Check ──────────────────────────────────────────────────

function checkAuth() {
    const token = localStorage.getItem('token');
    if (!token && window.location.pathname !== '/portal/login.html') {
        window.location.href = '/portal/login.html';
    }
    return token;
}

const token = checkAuth();

// ── Role-Based Access Control ──────────────────────────────────────────────

let _userRole = 'admin'; // default assumption until verified

async function loadUserRole() {
    try {
        const me = await api('GET', '/api/auth/me');
        if (me && me.role) {
            _userRole = me.role;
            if (_userRole === 'viewer') {
                applyViewerRestrictions();
            }
            // Show role badge in header if element exists
            const badge = document.getElementById('roleBadge');
            if (badge) {
                badge.textContent = _userRole === 'admin' ? '🛡️ Admin' : '👁️ Viewer';
                badge.title = _userRole === 'admin' ? 'Full access' : 'Read-only access';
            }
        }
    } catch (e) { /* silently ignore, default is admin */ }
}

function applyViewerRestrictions() {
    // All action buttons that are admin-only
    const adminOnlyIds = [
        'grantBtn', 'revokeBtn', 'checkBtn', 'sendShellBtn',
        'createUserBtn', 'sendNotificationBtn'
    ];
    adminOnlyIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.disabled = true;
            el.title = 'Admin role required';
            el.style.opacity = '0.4';
            el.style.cursor = 'not-allowed';
        }
    });
}

// ── Audit Log Export ───────────────────────────────────────────────────────

async function downloadAuditExport(format) {
    const t = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/v1/audit/export/${format}`, {
        headers: { 'Authorization': `Bearer ${t}` }
    });
    if (!res.ok) { toast('Export failed: ' + res.statusText, 'error'); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_log.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(`Audit log exported as ${format.toUpperCase()}`, 'success');
}



async function api(method, path, body = null) {
    const token = localStorage.getItem('token');
    const opts = {
        method,
        headers: { 
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    
    if (res.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/portal/login.html';
        return;
    }

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
    const box = $('resultBox');
    if (box) box.className = 'result-box';
}

// ── Utility Functions ──────────────────────────────────────────────────────

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    const day   = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year  = d.getFullYear();
    let hoursNum = d.getHours();
    const ampm = hoursNum >= 12 ? 'PM' : 'AM';
    hoursNum = hoursNum % 12 || 12;
    const hoursStr = String(hoursNum).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month}/${year} ${hoursStr}:${mins}:${secs} ${ampm}`;
}

function escapeHtml(str) {
    if (str == null) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

function escapeAttr(str) {
    if (str == null) return '';
    return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// Command History cache (for details modal)
let _historyCache = [];

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
        _deviceCache = devices;  // keep a copy for the System Info modal
        window._allDevices = devices; // expose for dashboard charts
        setConnected(true);
        // Update dashboard charts if the view is active
        if (typeof window.onDashboardDataLoaded === 'function') window.onDashboardDataLoaded();

        const select = $('deviceSelect');
        const filterSelect = $('filterDevice');
        const evtFilterSelect = $('evtFilterDevice');
        const blDeviceSelect = $('bitlockerDevice'); // Add bitlocker device select
        
        const currentVal = select.value;
        const currentFilterVal = filterSelect ? filterSelect.value : '';
        const currentEvtFilterVal = evtFilterSelect ? evtFilterSelect.value : '';
        const currentBlVal = blDeviceSelect ? blDeviceSelect.value : '';
        
        select.innerHTML = '<option value="">— Select a device —</option>';
        if (filterSelect) {
            filterSelect.innerHTML = '<option value="">All Devices</option>';
        }
        if (evtFilterSelect) {
            evtFilterSelect.innerHTML = '<option value="">All Devices</option>';
        }
        if (blDeviceSelect) {
            blDeviceSelect.innerHTML = '<option value="">— Select a device —</option>';
        }

        const now = new Date();
        devices.forEach(d => {
            const lastSeen = new Date(d.last_seen);
            const diff = now - lastSeen;
            // Online if seen in last 30s, or seen up to 1 min in the "future" (clock drift)
            const isOnline = diff < 30000 && diff > -60000; 
            const statusIcon = isOnline ? '🟢' : '🔴';

            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${statusIcon} ${d.hostname}  (${d.ip_address})`;
            select.appendChild(opt);

            if (filterSelect) {
                const fOpt = document.createElement('option');
                fOpt.value = d.id;
                fOpt.textContent = `${d.hostname} (${d.ip_address})`;
                filterSelect.appendChild(fOpt);
            }

            if (evtFilterSelect) {
                const eOpt = document.createElement('option');
                eOpt.value = d.id;
                eOpt.textContent = `${d.hostname} (${d.ip_address})`;
                evtFilterSelect.appendChild(eOpt);
            }

            if (blDeviceSelect) {
                const bOpt = document.createElement('option');
                bOpt.value = d.id;
                bOpt.textContent = `${d.hostname} (${d.ip_address})`;
                blDeviceSelect.appendChild(bOpt);
            }
        });

        if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) select.value = currentVal;
        if (filterSelect && currentFilterVal) filterSelect.value = currentFilterVal;
        if (evtFilterSelect && currentEvtFilterVal) evtFilterSelect.value = currentEvtFilterVal;
        if (blDeviceSelect && currentBlVal) blDeviceSelect.value = currentBlVal;

        // Rebuild notify device list checkboxes
        const notifyList = $('notifyDeviceList');
        if (notifyList) {
            const existingCheckboxes = Array.from(document.querySelectorAll('.notify-target-device:checked')).map(c => c.value);
            const isFirstLoad = document.querySelectorAll('.notify-target-device').length === 0;

            let html = `
                <div class="device-selector-container">
                    <div class="device-selector-header" onclick="document.getElementById('notifyTargetAllDevices').click()">
                        <input type="checkbox" id="notifyTargetAllDevices" value="All" ${isFirstLoad ? 'checked' : ''} onclick="event.stopPropagation()" onchange="const cbs=document.querySelectorAll('.notify-target-device'); cbs.forEach(c => c.checked = this.checked); updateNotifyCount(); loadNotifyCampaigns();">
                        <span style="flex:1">Target All Devices</span>
                    </div>
                    <div class="device-selector-list">
            `;
            devices.forEach(d => {
                const lastSeen = new Date(d.last_seen);
                const isOnline = (now - lastSeen) < 30000;
                const statusIcon = isOnline ? '🟢' : '🔴';
                const isChecked = isFirstLoad || existingCheckboxes.includes(d.id.toString());
                html += `
                    <div class="device-selector-item" onclick="const cb = this.querySelector('input'); cb.checked = !cb.checked; cb.dispatchEvent(new Event('change'));">
                        <input type="checkbox" class="notify-target-device" value="${d.id}" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation()" onchange="updateNotifyCount(); loadNotifyCampaigns();">
                        <label>${statusIcon} <strong>${d.hostname}</strong> <span style="color:var(--text-3); font-size:11px; margin-left:4px;">(${d.ip_address})</span></label>
                    </div>
                `;
            });
            html += '</div></div>';
            notifyList.innerHTML = html;
            updateNotifyCount();
        }

        // ── Helper: Update Notify Selected Count ──────────────────────────────────
function updateNotifyCount() {
    const checked = document.querySelectorAll('.notify-target-device:checked').length;
    const counter = $('notifyTargetCount');
    if (counter) counter.textContent = checked;
}

// Restore selection
        if (currentVal) select.value = currentVal;
        if (currentFilterVal && filterSelect) filterSelect.value = currentFilterVal;
        if (currentEvtFilterVal && evtFilterSelect) evtFilterSelect.value = currentEvtFilterVal;

        if ($('statDevices')) $('statDevices').textContent = devices.length;

        // Auto-refresh the System Info Modal silently if it is open
        const modal = $('sysInfoModal');
        if (modal && modal.classList.contains('show') && selectedDeviceId) {
            const activeDevice = devices.find(d => d.id == selectedDeviceId);
            if (activeDevice && activeDevice.system_info) {
                renderSysInfo($('sysInfoBody'), activeDevice.system_info);
            }
        }

    } catch {
        setConnected(false);
    }
}

// ── Device selection ───────────────────────────────────────────────────────
// (...) unchanged code up to Command History


let currentAdminList = [];

$('deviceSelect')?.addEventListener('change', function () {
    selectedDeviceId = this.value ? this.value : null;
    hideResult();
    if (selectedDeviceId) {
        populateUserDropdown();
        refreshAdminList();
    }
});

function populateUserDropdown() {
    const select = $('userSelect');
    if (!select || !selectedDeviceId) return;

    const device = _deviceCache.find(d => d.id == selectedDeviceId);
    if (!device || !device.all_users) {
        select.innerHTML = '<option value="">— User list unavailable —</option>';
        updateCommandButtons();
        return;
    }

    const currentVal = select.value;
    select.innerHTML = '<option value="">— Select a user —</option>';

    device.all_users.forEach(u => {
        const opt = document.createElement('option');
        opt.value = u.name;
        opt.textContent = `${u.enabled ? '👤' : '🚫'} ${u.name}`;
        select.appendChild(opt);
    });

    if (currentVal) select.value = currentVal;
    updateCommandButtons();
}

function updateCommandButtons() {
    const select = $('userSelect');
    const btnGrant = $('btnGrant');
    const btnRevoke = $('btnRevoke');
    
    if (!select || !btnGrant || !btnRevoke) return;

    const username = select.value;

    if (!username) {
        btnGrant.disabled = false;
        btnRevoke.disabled = false;
        btnGrant.style.opacity = '1';
        btnRevoke.style.opacity = '1';
        return;
    }

    const isAdmin = currentAdminList.includes(username);

    if (isAdmin) {
        btnGrant.disabled = true;
        btnGrant.style.opacity = '0.4';
        btnRevoke.disabled = false;
        btnRevoke.style.opacity = '1';
    } else {
        btnGrant.disabled = false;
        btnGrant.style.opacity = '1';
        btnRevoke.disabled = true;
        btnRevoke.style.opacity = '0.4';
    }
}

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
    const username = $('userSelect').value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Select a user', 'error'); return; }

    // Read optional expiry (datetime-local gives local time; convert to UTC ISO string)
    let expiresAt = null;
    const expiresAtInput = $('expiresAtInput');
    if (expiresAtInput && expiresAtInput.value) {
        expiresAt = new Date(expiresAtInput.value).toISOString();
    }

    try {
        showResult('info', '🔄', `Granting admin to "${username}"…`);
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'grant',
            username,
            expires_at: expiresAt,
        });

        const msg = expiresAt
            ? `Grant queued for "${username}" — auto-revoke at ${new Date(expiresAt).toLocaleString()}`
            : `Grant command queued for "${username}"`;
        toast(msg, 'success');
        showResult('success', '✅', msg);
        if (expiresAtInput) expiresAtInput.value = '';   // clear after sending
        loadHistory();
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

// ── Create User ────────────────────────────────────────────────────────────

function openCreateUserModal() {
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    $('newUserName').value = '';
    $('newUserPass').value = '';
    $('createUserModal').classList.add('show');
}

function closeCreateUserModal() {
    $('createUserModal').classList.remove('show');
}

async function submitCreateUser() {
    const username = $('newUserName').value.trim();
    const password = $('newUserPass').value;

    if (!username || !password) {
        toast('Username and password are required', 'error');
        return;
    }

    try {
        toast(`Creating user "${username}"…`, 'info');
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'create_user',
            username: username,
            payload: password
        });
        
        toast(`Create command queued for "${username}"`, 'success');
        closeCreateUserModal();
        loadHistory();
    } catch (e) {
        toast(`Failed to create user: ${e.message}`, 'error');
    }
}

async function revokeAdmin() {
    const username = $('userSelect').value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Select a user', 'error'); return; }

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

async function runShellCommand() {
    const payload = $('shellPayload').value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!payload) { toast('Enter a script payload', 'error'); return; }

    try {
        toast('Executing remote shell script…', 'info');
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'shell',
            payload: payload
        });
        toast('Shell command queued successfully', 'success');
        $('shellPayload').value = ''; // clear input
        loadHistory();
    } catch (e) {
        toast(e.message, 'error');
    }
}

// ── Notifications ──────────────────────────────────────────────────────────

function toggleNotifySchedule() {
    const isRecurring = $('notifyScheduleType').value === 'recurring';
    $('notifyRecurringOptions').style.display = isRecurring ? 'block' : 'none';
}

async function sendNotification() {
    const notifyCheckboxes = document.querySelectorAll('.notify-target-device:checked');
    const notifyDeviceIds = Array.from(notifyCheckboxes).map(c => c.value);

    if (notifyDeviceIds.length === 0) { toast('Select at least one target device', 'error'); return; }

    const message = $('notifyMessage').value.trim();
    if (!message) { toast('Enter a message', 'error'); return; }

    const targetUsers = ['All'];

    const isRecurring = $('notifyScheduleType').value === 'recurring';
    const stInput = $('notifyStartTime').value;
    const etInput = $('notifyEndTime').value;
    const interval = parseInt($('notifyInterval').value, 10);

    const payload = {
        device_ids: notifyDeviceIds,
        message,
        target_users: targetUsers,
        is_recurring: isRecurring
    };

    if (isRecurring) {
        if (!etInput) { toast('End Time is required for recurring campaigns', 'error'); return; }
        if (isNaN(interval) || interval < 1) { toast('Invalid interval', 'error'); return; }
        
        let st = stInput ? new Date(stInput) : new Date();
        let et = new Date(etInput);
        
        payload.start_time = st.toISOString();
        payload.end_time = et.toISOString();
        payload.interval_minutes = interval;
    }

    try {
        await api('POST', '/api/v1/notifications', payload);
        toast(isRecurring ? 'Recurring notification campaign created!' : 'Notification command queued!', 'success');
        $('notifyMessage').value = '';
        if (isRecurring) loadNotifyCampaigns();
        loadHistory();
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function loadNotifyCampaigns() {
    let checkedDevices = Array.from(document.querySelectorAll('.notify-target-device:checked')).map(c => c.value);
    const tbody = $('notifyCampaignsBody');
    if (!tbody) return;

    // If nothing checked, show all for convenience or "No active" message
    if (checkedDevices.length === 0 && _deviceCache && _deviceCache.length > 0) {
        checkedDevices = _deviceCache.map(d => d.id.toString());
    }

    if (checkedDevices.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:15px; font-size:12px;">No active devices found.</div></td></tr>`;
        return;
    }

    try {
        let allCampaigns = [];
        for (const devId of checkedDevices) {
            try {
                const resp = await api('GET', `/api/v1/notifications/${devId}`);
                if (resp && resp.campaigns) {
                    const devObj = _deviceCache.find(d => d.id == devId);
                    const hostname = devObj ? devObj.hostname : devId;
                    resp.campaigns.forEach(c => { c.target_hostname = hostname; });
                    allCampaigns = allCampaigns.concat(resp.campaigns);
                }
            } catch (innerErr) {
                console.warn(`Failed to fetch for ${devId}`, innerErr);
            }
        }
        
        tbody.innerHTML = '';
        if (allCampaigns.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:15px; font-size:12px;">No active campaigns found.</div></td></tr>`;
            return;
        }

        for (const c of allCampaigns) {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(c.target_hostname)}</td>
                <td>${escapeHtml(c.message)}</td>
                <td><span class="badge badge-info">${escapeHtml(c.target_users.join(', '))}</span></td>
                <td>Every ${c.interval_minutes}m</td>
                <td>${formatDate(c.end_time)}</td>
                <td>
                    <button class="btn btn-danger" style="padding:4px 8px; font-size:11px;" onclick="cancelNotifyCampaign(${c.id})">Cancel</button>
                </td>
            `;
            tbody.appendChild(tr);
        }
    } catch(e) { 
        console.error("loadNotifyCampaigns failed", e);
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:15px; font-size:12px; color:var(--danger);">Error loading campaigns.</div></td></tr>`;
    }
}

async function cancelNotifyCampaign(id) {
    if (!confirm('Cancel this recurring notification campaign?')) return;
    try {
        await api('DELETE', `/api/v1/notifications/${id}`);
        toast('Campaign cancelled', 'success');
        loadNotifyCampaigns();
    } catch(e) {
        toast(e.message, 'error');
    }
}

// ── Interactive Terminal ───────────────────────────────────────────────────

let termFitAddon = null;
let termOnDataDisposable = null;

function openTerminal() {
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }

    const modal = $('terminalModal');
    modal.classList.add('show');

    // Always destroy and re-create a fresh terminal instance each open
    if (term) {
        term.dispose();
        term = null;
        termFitAddon = null;
    }

    term = new Terminal({
        theme: {
            background: '#0d0d0d',
            foreground: '#f1f5f9',
            cursor: '#22d3ee',
            selection: 'rgba(34,211,238,0.25)',
            black: '#0d0d0d',
        },
        fontFamily: '"Cascadia Code", "Fira Code", "Courier New", monospace',
        fontSize: 14,
        lineHeight: 1.3,
        cursorBlink: true,
        cursorStyle: 'bar',
        scrollback: 5000,
        // NOTE: convertEol intentionally NOT set — the PTY handles line endings
        //       Setting it to true causes a stray blank line after every Enter.
    });

    // Auto-fit the terminal to the container dimensions
    termFitAddon = new FitAddon.FitAddon();
    term.loadAddon(termFitAddon);
    term.open($('terminalContainer'));

    // Helper: send the current terminal dimensions to the agent so the PTY
    // can resize to match, eliminating the blank-space-above-prompt bug.
    function _sendResize() {
        if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN && term) {
            terminalSocket.send(`\x1bPTYR:${term.rows}:${term.cols}`);
        }
    }

    // Fit once, then focus and send resize to agent
    requestAnimationFrame(() => {
        termFitAddon.fit();
        term.focus();         // Auto-focus so typing works immediately
        _sendResize();
    });

    const _resizer = () => {
        if (termFitAddon) {
            termFitAddon.fit();
            _sendResize();
        }
    };
    window.addEventListener('resize', _resizer);

    // Close old socket
    if (terminalSocket) { terminalSocket.close(); terminalSocket = null; }

    terminalSocket = new WebSocket(`${WS_BASE}/ws/portal/${selectedDeviceId}`);

    terminalSocket.onopen = () => {
        // Fit again now that the socket is live, then send resize so PTY matches
        if (termFitAddon) termFitAddon.fit();
        term.focus();
        _sendResize();
        // Write a subtle connection notice (cyan, dim)
        term.writeln('\x1b[2;36mConnected — session active\x1b[0m');
    };

    let hasReceivedPtyData = false;
    terminalSocket.onmessage = (event) => {
        if (!hasReceivedPtyData) {
            hasReceivedPtyData = true;
            // The agent has finally connected and spawned the PTY.
            // Send our exact xterm size now so ConPTY redraws the prompt perfectly!
            _sendResize();
        }
        term.write(event.data);
        term.scrollToBottom();
    };

    terminalSocket.onclose = () => {
        if (term) term.writeln('\r\n\x1b[31mConnection closed by server.\x1b[0m\r\n');
    };

    terminalSocket.onerror = () => {
        if (term) term.writeln('\r\n\x1b[31mWebSocket error — check server.\x1b[0m\r\n');
    };

    // Auto-copy on text selection
    term.onSelectionChange(() => {
        const selection = term.getSelection();
        if (selection) {
            navigator.clipboard.writeText(selection).catch(err => {
                console.warn('Clipboard write failed:', err);
            });
        }
    });

    // Paste from clipboard on Right Click
    term.element.addEventListener('contextmenu', async (e) => {
        e.preventDefault();
        try {
            const text = await navigator.clipboard.readText();
            if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN && text) {
                terminalSocket.send(text);
            }
        } catch (err) {
            console.warn('Clipboard read failed:', err);
            toast('Failed to read clipboard', 'error');
        }
    });

    // Custom key handler for Command Cancellation
    term.attachCustomKeyEventHandler(e => {
        if (e.type === 'keydown' && e.ctrlKey) {
            const key = e.key.toLowerCase();
            // Let native Ctrl+C copy text if there is an active selection
            if (key === 'c' && term.hasSelection()) {
                return false; 
            }
            // If Ctrl+C (no selection) OR Ctrl+X, explicitly send an interrupt/cancel signal (\x03)
            if (key === 'c' || key === 'x') {
                if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN) {
                    terminalSocket.send('\x03');
                }
                e.preventDefault();
                return false; // Stop xterm from further processing
            }
        }
        return true;
    });

    // Send keystrokes and native standard pastes to the agent via WebSocket
    termOnDataDisposable = term.onData(data => {
        if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN) {
            terminalSocket.send(data);
        }
    });

    // Store resize handler so we can remove it on close
    modal._resizer = _resizer;
}

function closeTerminal() {
    const modal = $('terminalModal');
    modal.classList.remove('show');

    if (modal._resizer) {
        window.removeEventListener('resize', modal._resizer);
        modal._resizer = null;
    }
    if (terminalSocket) {
        terminalSocket.close();
        terminalSocket = null;
    }
    if (term) {
        term.dispose();
        term = null;
        termFitAddon = null;
    }
}

// ── Admin List ─────────────────────────────────────────────────────────────

async function refreshAdminList() {
    if (!selectedDeviceId) return;

    try {
        const data = await api('GET', `/admin_list/${selectedDeviceId}`);
        const tbody = $('adminTableBody');

        if (!data.admin_users || data.admin_users.length === 0) {
            currentAdminList = [];
            tbody.innerHTML = `<tr><td colspan="3">
                <div class="empty-state">
                    <span class="icon">📋</span>
                    No admin data yet — click Check Status
                </div>
            </td></tr>`;
            if ($('statAdmins')) $('statAdmins').textContent = '0';
            updateCommandButtons();
            return;
        }

        currentAdminList = data.admin_users;
        if ($('statAdmins')) $('statAdmins').textContent = data.admin_users.length;
        updateCommandButtons();

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
    const select = $('userSelect');
    if (select) {
        // Attempt to select the user in the dropdown, but if they aren't in all_users,
        // we might not match. Just set the value anyway.
        select.innerHTML = `<option value="${escapeAttr(username)}">${escapeHtml(username)}</option>` + select.innerHTML;
        select.value = username;
        updateCommandButtons();
    }
    revokeAdmin();
}

// ── Command History ────────────────────────────────────────────────────────

let currentHistoryPage = 1;
let historyLimit = 20;
let sortColumn = 'created_at';
let sortDirection = 'desc';

function changeLimit() {
    const selector = $('limitSelect');
    if (selector) {
        historyLimit = parseInt(selector.value, 10) || 20;
    }
    currentHistoryPage = 1;
    loadHistory();
}

function jumpToPage() {
    const input = $('pageJumpInput');
    if (input) {
        let desired = parseInt(input.value, 10);
        if (isNaN(desired) || desired < 1) desired = 1;
        // The max value check is handled gracefully by the backend offset logic, but we can set it here too if we want
        currentHistoryPage = desired;
        loadHistory();
    }
}

function sortBy(col) {
    if (sortColumn === col) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn = col;
        sortDirection = 'asc'; // default to asc when switching columns
    }
    loadHistory();
}

function applyFilters() {
    currentHistoryPage = 1; // reset page on new filter
    loadHistory();
}

function clearFilters() {
    if ($('filterDevice')) $('filterDevice').value = '';
    if ($('filterAction')) $('filterAction').value = '';
    if ($('filterStatus')) $('filterStatus').value = '';
    if ($('filterSearch')) $('filterSearch').value = '';
    currentHistoryPage = 1;
    loadHistory();
}

function changePage(delta) {
    currentHistoryPage += delta;
    if (currentHistoryPage < 1) currentHistoryPage = 1;
    loadHistory();
}

async function loadHistory() {
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

        const data = await api('GET', url);
        const history = data.commands || [];
        
        // Auto-refresh detection:
        // If the current selected device has any commands that just reached 'completed', refresh admin list
        if (selectedDeviceId) {
            const completedRecently = history.filter(c => 
                c.device_id == selectedDeviceId && 
                c.status === 'completed' &&
                ['grant', 'revoke', 'check', 'create_user'].includes(c.action)
            );
            
            // If we find completed missions that haven't been "seen" by our current state yet, refresh
            // We use the ID to avoid double-refreshing within the same poll cycle
            if (completedRecently.length > 0) {
                const latestId = Math.max(...completedRecently.map(c => c.id));
                if (window._lastAutoRefreshId !== latestId) {
                    window._lastAutoRefreshId = latestId;
                    console.log(`[Auto-Refresh] Command #${latestId} completed. Refreshing admin list...`);
                    refreshAdminList();
                }
            }
        }

        _historyCache = history; // Cache for details modal
        const total = data.total || 0;
        const page = data.page || 1;
        const limit = data.limit || 20;

        const tbody = $('historyTableBody');

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No commands found</div>
            </td></tr>`;
            if ($('statCommands')) $('statCommands').textContent = '0';
            // Update Pagination UI
            if ($('pageInfoText')) $('pageInfoText').textContent = '0 results';
            if ($('pageIndicator')) $('pageIndicator').textContent = '1';
            if ($('btnPrevPage')) $('btnPrevPage').disabled = true;
            if ($('btnNextPage')) $('btnNextPage').disabled = true;
            return;
        }

        const completedCount = history.filter(c => c.status === 'completed').length;
        if ($('statCommands')) $('statCommands').textContent = completedCount;

        // Update Pagination UI
        const totalPages = Math.ceil(total / limit) || 1;
        if ($('pageInfoText')) {
            const startIdx = total === 0 ? 0 : ((page - 1) * limit) + 1;
            const endIdx = Math.min(page * limit, total);
            $('pageInfoText').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }
        if ($('totalPagesSpan')) $('totalPagesSpan').textContent = totalPages;
        if ($('pageJumpInput')) {
            $('pageJumpInput').max = totalPages;
            $('pageJumpInput').value = page;
        }
        if ($('btnPrevPage')) $('btnPrevPage').disabled = (page <= 1);
        if ($('btnNextPage')) $('btnNextPage').disabled = (page >= totalPages);

        // Update Sort Icons
        const columns = ['id', 'device_hostname', 'action', 'username', 'status', 'result', 'created_at'];
        for (const c of columns) {
            const el = $(`sort-idx-${c}`);
            if (el) {
                if (c === sortColumn) {
                    el.textContent = sortDirection === 'asc' ? '▲' : '▼';
                    el.style.color = 'var(--accent)';
                } else {
                    el.textContent = '';
                    el.style.color = '';
                }
            }
        }

        tbody.innerHTML = history.map(c => {
            const actionIcons = { grant: '✅', revoke: '🚫', check: '🔍', shell: '💻', create_user: '👤', notify: '📢' };
            const statusClass = `badge-${c.status}`;
            
            let actionText = c.action;
            if (c.action === 'grant') {
                if (c.expires_at) {
                    const created = new Date(c.created_at);
                    const expires = new Date(c.expires_at);
                    const diffMins = Math.round((expires - created) / 60000);
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

            // Build expiry badge for grant commands
            let expiryBadge = '';
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
                    const durationMs = new Date(c.expires_at).getTime() - new Date(c.created_at).getTime();
                    const durationMins = Math.round(durationMs / 60000);
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
    } catch {
        // silent
    }
}

function openCmdDetailsModal(cmdId) {
    const cmd = _historyCache.find(c => c.id === cmdId);
    if (!cmd) return;

    if ($('cmdModalId')) $('cmdModalId').textContent = `#${cmd.id}`;
    if ($('cmdModalDevice')) $('cmdModalDevice').textContent = `${cmd.device_hostname || 'Unknown'} (${cmd.device_id})`;
    if ($('cmdModalAction')) $('cmdModalAction').textContent = cmd.action.replace('_', ' ');
    if ($('cmdModalTarget')) $('cmdModalTarget').textContent = cmd.username || '—';
    if ($('cmdModalTime')) $('cmdModalTime').textContent = formatDate(cmd.created_at);
    if ($('cmdModalPayload')) $('cmdModalPayload').textContent = cmd.payload || 'None';
    if ($('cmdModalResult')) $('cmdModalResult').textContent = cmd.result || 'No result yet';

    $('cmdDetailsModal').classList.add('show');
}

function closeCmdDetailsModal(event) {
    if (event && event.target !== event.currentTarget) return;
    $('cmdDetailsModal').classList.remove('show');
}

// ── Event Log Monitor ──────────────────────────────────────────────────────

let evtCurrentPage = 1;
let evtLimit = 20;
let evtSortColumn = 'timestamp';
let evtSortDirection = 'desc';

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

function applyEventFilters() {
    evtCurrentPage = 1;
    loadEventLogs();
}

function clearEventFilters() {
    if ($('evtFilterDevice')) $('evtFilterDevice').value = '';
    if ($('evtFilterSource')) $('evtFilterSource').value = '';
    if ($('evtFilterEventId')) $('evtFilterEventId').value = '';
    if ($('evtFilterSearch')) $('evtFilterSearch').value = '';
    evtCurrentPage = 1;
    loadEventLogs();
}

function changeEventPage(delta) {
    evtCurrentPage += delta;
    if (evtCurrentPage < 1) evtCurrentPage = 1;
    loadEventLogs();
}

function changeEventLimit() {
    const sel = $('evtLimitSelect');
    if (sel) evtLimit = parseInt(sel.value, 10) || 20;
    evtCurrentPage = 1;
    loadEventLogs();
}

function jumpToEventPage() {
    const input = $('evtPageJumpInput');
    if (input) {
        let desired = parseInt(input.value, 10);
        if (isNaN(desired) || desired < 1) desired = 1;
        evtCurrentPage = desired;
        loadEventLogs();
    }
}

function sortEventsBy(col) {
    if (evtSortColumn === col) {
        evtSortDirection = evtSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        evtSortColumn = col;
        evtSortDirection = 'asc';
    }
    loadEventLogs();
}

async function loadEventLogs() {
    try {
        let url = `/api/v1/event-logs?limit=${evtLimit}&page=${evtCurrentPage}&sort_by=${encodeURIComponent(evtSortColumn)}&sort_dir=${encodeURIComponent(evtSortDirection)}`;

        const device = $('evtFilterDevice')?.value;
        const source = $('evtFilterSource')?.value;
        const eventId = $('evtFilterEventId')?.value;
        const search = $('evtFilterSearch')?.value;

        if (device) url += `&device_id=${encodeURIComponent(device)}`;
        if (source) url += `&log_source=${encodeURIComponent(source)}`;
        if (eventId) url += `&event_id=${encodeURIComponent(eventId)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const data = await api('GET', url);
        const logs = data.logs || [];
        const total = data.total || 0;
        const page = data.page || 1;
        const limit = data.limit || 20;

        const tbody = $('eventLogTableBody');

        if (logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No event logs found</div>
            </td></tr>`;
            if ($('evtPageInfoText')) $('evtPageInfoText').textContent = '0 results';
            if ($('evtTotalPagesSpan')) $('evtTotalPagesSpan').textContent = '1';
            if ($('evtPageJumpInput')) $('evtPageJumpInput').value = 1;
            if ($('btnEvtPrevPage')) $('btnEvtPrevPage').disabled = true;
            if ($('btnEvtNextPage')) $('btnEvtNextPage').disabled = true;
            return;
        }

        // Update pagination
        const totalPages = Math.ceil(total / limit) || 1;
        if ($('evtPageInfoText')) {
            const startIdx = total === 0 ? 0 : ((page - 1) * limit) + 1;
            const endIdx = Math.min(page * limit, total);
            $('evtPageInfoText').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }
        if ($('evtTotalPagesSpan')) $('evtTotalPagesSpan').textContent = totalPages;
        if ($('evtPageJumpInput')) {
            $('evtPageJumpInput').max = totalPages;
            $('evtPageJumpInput').value = page;
        }
        if ($('btnEvtPrevPage')) $('btnEvtPrevPage').disabled = (page <= 1);
        if ($('btnEvtNextPage')) $('btnEvtNextPage').disabled = (page >= totalPages);

        // Update sort icons
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

        // Render table
        tbody.innerHTML = logs.map(evt => {
            let timeStr = evt.timestamp;
            if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
            const time = formatDate(timeStr);
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
    } catch {
        // silent
    }
}

async function loadEventLogSummary() {
    try {
        const data = await api('GET', '/api/v1/event-logs/summary');
        if ($('statTotalEvents')) $('statTotalEvents').textContent = data.total_events || 0;
        if ($('statLogins')) $('statLogins').textContent = data.logins || 0;
        if ($('statLogoffs')) $('statLogoffs').textContent = data.logoffs || 0;
        if ($('statCrashes')) $('statCrashes').textContent = data.crashes || 0;
        if ($('statPrivilegeEvents')) $('statPrivilegeEvents').textContent = data.privilege_events || 0;
    } catch {
        // silent
    }
}

// ── Utilities ──────────────────────────────────────────────────────────────

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    
    let hoursNum = d.getHours();
    const ampm = hoursNum >= 12 ? 'PM' : 'AM';
    hoursNum = hoursNum % 12;
    hoursNum = hoursNum ? hoursNum : 12; // the hour '0' should be '12'
    const hoursStr = String(hoursNum).padStart(2, '0');
    
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month}/${year} ${hoursStr}:${mins}:${secs} ${ampm}`;
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}



// ── Event Log Details Modal ──────────────────────────────────────────────────

function openLogDetailsModal(evt) {
    if (!evt) return;
    
    // Populate modal fields
    if ($('logModalEventId')) $('logModalEventId').textContent = evt.event_id || '—';
    if ($('logModalSource')) {
        $('logModalSource').textContent = evt.log_source || '—';
        const sourceBadgeColors = { Security: 'var(--danger)', System: 'var(--warning)', Application: 'var(--accent)' };
        $('logModalSource').style.color = sourceBadgeColors[evt.log_source] || 'var(--text-secondary)';
    }
    
    let timeStr = evt.timestamp;
    if (timeStr && !timeStr.endsWith('Z')) timeStr += 'Z';
    const time = formatDate(timeStr);
    if ($('logModalTime')) $('logModalTime').textContent = time;
    
    if ($('logModalDevice')) $('logModalDevice').textContent = evt.hostname || '—';
    if ($('logModalUser')) $('logModalUser').textContent = evt.username || '—';
    
    if ($('logModalMessage')) $('logModalMessage').textContent = evt.message || 'No additional details provided.';
    
    // Show modal
    const modal = $('logDetailsModal');
    if (modal) modal.classList.add('show');
}

function closeLogDetailsModal() {
    const modal = $('logDetailsModal');
    if (modal) modal.classList.remove('show');
}

// ── System Info Modal ─────────────────────────────────────────────────────


function openSysInfoModal() {
    const deviceId = selectedDeviceId;
    if (!deviceId) {
        showToast('Select a device first.', 'warn');
        return;
    }

    const device = _deviceCache.find(d => d.id == deviceId);
    const hostname = device ? device.hostname : deviceId;
    document.getElementById('sysInfoDeviceName').textContent = hostname;
    
    // Set status badge
    const badgeEl = document.getElementById('sysInfoStatusBadge');
    if (badgeEl && device) {
        const diff = Date.now() - new Date(device.last_seen);
        const isOn = device.last_seen && diff < 30 * 1000 && diff > -60 * 1000;
        badgeEl.innerHTML = isOn 
            ? `<span class="badge badge-completed"><span class="badge-dot"></span>Online</span>`
            : `<span class="badge badge-failed"><span class="badge-dot"></span>Offline</span>`;
    } else if (badgeEl) {
        badgeEl.innerHTML = '';
    }

    const modal = document.getElementById('sysInfoModal');
    modal.classList.add('show');

    const body = document.getElementById('sysInfoBody');

    if (!device || !device.system_info) {
        body.innerHTML = `<div style="text-align:center;color:var(--text-secondary);padding:40px;">
            No system info collected yet.<br>
            <small>The agent sends this data on startup. Make sure the agent is running.</small>
        </div>`;
        return;
    }

    renderSysInfo(body, device.system_info, deviceId);
}

function closeSysInfoModal(e) {
    if (e && e.target !== document.getElementById('sysInfoModal')) return;
    document.getElementById('sysInfoModal').classList.remove('show');
}

function renderSysInfo(container, info, deviceId) {
    const pct = (v, total) => {
        const p = total > 0 ? Math.min(100, Math.round((v / total) * 100)) : 0;
        const color = p > 85 ? '#ef4444' : p > 60 ? '#f59e0b' : '#10b981';
        return `<div class="sysinfo-bar-wrap">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-secondary);margin-bottom:3px;">
                <span>${p}% used</span><span>${(total - v).toFixed(1)} free</span>
            </div>
            <div class="sysinfo-bar-track"><div class="sysinfo-bar-fill" style="width:${p}%;background:${color};"></div></div>
        </div>`;
    };

    const row = (label, value) => `
        <div class="sysinfo-row">
            <span class="sysinfo-label">${label}</span>
            <span class="sysinfo-value">${value ?? '—'}</span>
        </div>`;

    const ramUsed = (info.ram_total_gb || 0) - (info.ram_free_gb || 0);

    // Disks
    const disks = Array.isArray(info.disks) ? info.disks : (info.disks ? [info.disks] : []);
    const disksHtml = disks.map(d => {
        const blStatus = d.bitlocker || '0% (Off)';
        const convStatus = d.bl_status || 'Ready';
        const isEncrypted = blStatus.toLowerCase().includes('on') || (blStatus.includes('%') && !blStatus.startsWith('0%'));
        
        const blColor = isEncrypted ? 'var(--success)' : 'var(--text-secondary)';
        const blIcon = isEncrypted ? '🔒' : '🔓';

        const keyBtn = isEncrypted ? 
            `<button class="btn btn-sm" style="margin-top:10px; width:100%; justify-content:center; background:var(--bg); border:1px solid var(--accent); color:var(--accent); font-weight:700;" 
                     onclick="getBitLockerKey('${deviceId}', '${escapeAttr(d.drive)}')">🔑 Get Recovery Key</button>` : '';

        return `
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">💾 Storage — ${d.drive}</div>
            ${row('Total', `${d.size_gb} GB`)}
            ${row('Free', `${d.free_gb} GB`)}
            ${row('BitLocker', `<span style="color:${blColor}; font-weight:600;">${blIcon} ${blStatus}</span>`)}
            ${row('Conv. Status', `<small style="color:var(--text-muted)">${convStatus}</small>`)}
            ${keyBtn}
            ${pct(d.size_gb - d.free_gb, d.size_gb)}
        </div>`;
    }).join('');

    // Network
    const nics = Array.isArray(info.network) ? info.network : (info.network ? [info.network] : []);
    const nicsHtml = nics.map(n => `
        <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.04); padding-bottom: 6px;">
            <div style="font-size:11px; color:var(--text-secondary); margin-bottom:4px;">${n.description || 'Adapter'}</div>
            ${row('IPv4 Address', n.ip || '—')}
            ${row('MAC Address', n.mac || '—')}
        </div>`).join('');

    container.innerHTML = `<div class="sysinfo-grid">
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🖥️ System</div>
            ${row('Hostname', info.hostname)}
            ${row('Logged-in User', info.logged_user)}
            ${row('Manufacturer', info.manufacturer)}
            ${row('Model', info.model)}
            ${row('Serial', info.serial_number)}
            ${row('BIOS', info.bios_version)}
            ${row('Uptime', info.uptime)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">⚙️ OS</div>
            ${row('OS Name', info.os_name)}
            ${row('Version', info.os_version)}
            ${row('Architecture', info.os_arch)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🧠 CPU</div>
            ${row('Processor', info.cpu_name)}
            ${row('Cores', info.cpu_cores)}
            ${row('Current Load', info.cpu_load_pct != null ? `${info.cpu_load_pct}%` : '—')}
            ${pct(info.cpu_load_pct || 0, 100)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🗄️ RAM</div>
            ${row('Total RAM', `${info.ram_total_gb} GB`)}
            ${row('Used RAM', `${ramUsed.toFixed(2)} GB`)}
            ${row('Free RAM', `${(info.ram_free_gb || 0).toFixed(2)} GB`)}
            ${pct(ramUsed, info.ram_total_gb || 1)}
        </div>
        ${disksHtml}
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">🌐 Network</div>
            ${nicsHtml || row('Status', 'No active adapters found')}
        </div>
    </div>`;
}

async function getBitLockerKey(deviceId, driveLetter) {
    try {
        console.log(`[getBitLockerKey] Fetching key for Device ID: ${deviceId}, Drive: ${driveLetter}`);

        // Fallback to selectedDeviceId if deviceId is missing or "undefined" string
        const targetId = (deviceId && deviceId !== 'undefined') ? deviceId : selectedDeviceId;

        if (!targetId) {
            toast('No device context found. Please re-select the device.', 'error');
            return;
        }

        const cachedDevice = _deviceCache.find(d => d.id == targetId);
        if (!cachedDevice || !cachedDevice.system_info) {
            console.error('[getBitLockerKey] Device not found in cache for ID:', targetId);
            toast('Device data not available in cache. Try clicking Refresh.', 'error');
            return;
        }

        const info = typeof cachedDevice.system_info === 'string' ? JSON.parse(cachedDevice.system_info) : cachedDevice.system_info;
        const disks = Array.isArray(info.disks) ? info.disks : (info.disks ? [info.disks] : []);
        const targetDisk = disks.find(d => d.drive === driveLetter);

        if (!targetDisk) {
            toast(`Drive ${driveLetter} not found on this device`, 'error');
            return;
        }

        const recoveryKey = targetDisk.recovery_key;
        if (!recoveryKey || recoveryKey === 'Not Encrypted' || recoveryKey === 'Not encrypted') {
            toast(`Drive ${driveLetter} is not BitLocker encrypted`, 'info');
        } else if (recoveryKey === 'Not found' || recoveryKey.startsWith('Failed') || (typeof recoveryKey === 'string' && recoveryKey.includes('Key not found'))) {
            toast(`Key not yet synced. The agent is fetching it.`, 'warning');
        } else {
            // Populate and show custom modal
            document.getElementById('bkModalDevice').textContent = cachedDevice.hostname;
            document.getElementById('bkModalDrive').textContent = driveLetter;
            document.getElementById('bkModalKey').textContent = recoveryKey;
            
            document.getElementById('bitlockerKeyModal').classList.add('show');
        }
    } catch (e) {
        console.error('[getBitLockerKey] Error:', e);
        toast('Error reading key data', 'error');
    }
}

function closeBitLockerKeyModal() {
    document.getElementById('bitlockerKeyModal').classList.remove('show');
}

async function getBitLockerKeyStandalone() {
    const deviceId = $('bitlockerDevice')?.value || selectedDeviceId || $('deviceSelect')?.value;
    if (!deviceId) { toast('Select a target device first', 'error'); return; }

    const driveInput = $('bitlockerDrive');
    let drive = (driveInput?.value || '').trim().toUpperCase();
    if (!drive) { toast('Enter a drive letter (e.g. C:)', 'error'); return; }
    if (drive.length === 1) drive += ':';

    getBitLockerKey(deviceId, drive);
    driveInput.value = '';
}

// ── Dashboard Data ─────────────────────────────────────────────────────────

async function fetchAllCommandsForDashboard() {
    try {
        const data = await api('GET', '/commands/history?limit=10000');
        window._allCommands = data.commands || [];
        if (typeof window.onDashboardDataLoaded === 'function') window.onDashboardDataLoaded();
    } catch (e) {
        console.error('fetchAllCommandsForDashboard error:', e);
    }
}

async function fetchAllAdminsCount() {
    try {
        const devices = window._allDevices || [];
        let count = 0;
        for (const d of devices) {
            const data = await api('GET', `/admin_list/${d.id}`);
            if (data && data.admin_users) {
                count += data.admin_users.length;
            }
        }
        if (document.getElementById('dash-active-admins')) {
            document.getElementById('dash-active-admins').textContent = count;
        }
    } catch (e) {
        console.error('fetchAllAdminsCount error', e);
    }
}

// ── Polling ────────────────────────────────────────────────────────────────

async function pollAll() {
    await loadDevices();
    await fetchAllCommandsForDashboard();
    await loadHistory();
    await loadEventLogs();
    await loadEventLogSummary();
    await loadNotifyCampaigns();
    await fetchAllAdminsCount();
    if (selectedDeviceId) await refreshAdminList();
}

// Initial load
loadUserRole();  // Apply RBAC immediately
pollAll();

// Auto-refresh every 5 seconds
pollInterval = setInterval(pollAll, 5000);
