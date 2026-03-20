/**
 * Admin Control System — Dashboard Logic
 * Handles all API communication, UI updates, and polling.
 */

const API_BASE = window.location.origin;
const WS_BASE = window.location.origin.replace('http', 'ws');
let selectedDeviceId = null;
let pollInterval = null;
let _deviceCache = [];  // cache of all devices with their all_users payload
let _latestAgentVersion = null;
let _lastVersionFetch = 0;
let activityPage = 1;
let activityLimit = 20;

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

// ── Logout Modal Helpers ──────────────────────────────────────────────────

function showLogoutModal() {
    const m = document.getElementById('logoutModal');
    if (m) m.classList.add('show');
}

function hideLogoutModal() {
    const m = document.getElementById('logoutModal');
    if (m) m.classList.remove('show');
}

function performLogout() {
    localStorage.removeItem('token');
    window.location.href = '/portal/login.html';
}

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
        'btnGrant', 'btnRevoke', 'btnCheck', 'sendShellBtn', 'openTerminalBtn',
        'btnCreateUser', 'sendNotificationBtn', 'btnGenerateOtp', 'btnUploadVersion'
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
    if (!t) {
        toast('Your session has expired. Please sign in again.', 'error');
        window.location.href = '/portal/login.html';
        return;
    }

    const btnId = format === 'csv' ? 'btnExportCsv' : 'btnExportPdf';
    const btn = document.getElementById(btnId);
    const originalText = btn ? btn.textContent : '';

    try {
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Preparing...';
        }

        // Use direct download so the browser honors Content-Disposition for filename.
        const url = `${API_BASE}/api/v1/audit/export/${format}?token=${encodeURIComponent(t)}`;
        const iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        iframe.src = url;
        document.body.appendChild(iframe);

        window.setTimeout(() => {
            if (iframe.parentNode) iframe.remove();
        }, 10000);

        toast(`Download starting: audit_log.${format.toUpperCase()}`, 'success');
    } catch (err) {
        toast(err.message || 'Export failed', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
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
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    let hoursNum = d.getHours();
    const ampm = hoursNum >= 12 ? 'PM' : 'AM';
    hoursNum = hoursNum % 12 || 12;
    const hoursStr = String(hoursNum).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month}/${year} ${hoursStr}:${mins}:${secs} ${ampm}`;
}

function semverCompare(a, b) {
    const pa = (a || '').split('.').map(n => parseInt(n, 10) || 0);
    const pb = (b || '').split('.').map(n => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
        if ((pa[i] || 0) > (pb[i] || 0)) return 1;
        if ((pa[i] || 0) < (pb[i] || 0)) return -1;
    }
    return 0;
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
        const activitySelect = $('activityDevice');
        const otpSelect = $('otpDeviceSelect');
        const patchSelect = $('patchDeviceSelect');

        const currentVal = select.value;
        const currentFilterVal = filterSelect ? filterSelect.value : '';
        const currentEvtFilterVal = evtFilterSelect ? evtFilterSelect.value : '';
        const currentBlVal = blDeviceSelect ? blDeviceSelect.value : '';
        const currentActVal = activitySelect ? activitySelect.value : '';
        const currentOtpVal = otpSelect ? otpSelect.value : '';
        const currentPatchVal = patchSelect ? patchSelect.value : '';

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
        if (activitySelect) {
            activitySelect.innerHTML = '<option value="">All devices</option>';
        }
        if (otpSelect) {
            otpSelect.innerHTML = '<option value=\"\">— Select a device —</option>';
        }
        if (patchSelect) {
            patchSelect.innerHTML = '<option value=\"\">All devices</option>';
        }

        const now = new Date();
        devices.forEach(d => {
            const lastSeen = new Date(d.last_seen);
            const diff = now - lastSeen;
            // Online if seen in last 30s, or seen up to 1 min in the "future" (clock drift)
            const isOnline = !d.is_uninstalled && diff < 30000 && diff > -60000;
            const isUninstalled = d.is_uninstalled;
            const statusIcon = isUninstalled ? '⬜' : (isOnline ? '🟢' : '🔴');

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
                
                let isEncrypted = false;
                if (d.system_info && d.system_info !== 'null') {
                    const infoStr = typeof d.system_info === 'string' ? d.system_info : JSON.stringify(d.system_info);
                    isEncrypted = infoStr.includes('Protection On') || infoStr.includes('Percentage Encrypted');
                }
                
                bOpt.textContent = `${d.hostname} (${d.ip_address}) ${isEncrypted ? '🔐' : ''}`;
                if (isEncrypted) bOpt.style.fontWeight = 'bold';
                
                blDeviceSelect.appendChild(bOpt);
            }

            if (activitySelect) {
                const aOpt = document.createElement('option');
                aOpt.value = d.id;
                aOpt.textContent = `${d.hostname} (${d.ip_address})`;
                activitySelect.appendChild(aOpt);
            }

            if (otpSelect) {
                const o = document.createElement('option');
                o.value = d.id;
                o.textContent = `${d.hostname} (${d.ip_address})`;
                otpSelect.appendChild(o);
            }

            if (patchSelect) {
                const p = document.createElement('option');
                p.value = d.id;
                p.textContent = `${d.hostname} (${d.ip_address})`;
                patchSelect.appendChild(p);
            }
        });

        if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) select.value = currentVal;
        if (filterSelect && currentFilterVal) filterSelect.value = currentFilterVal;
        if (evtFilterSelect && currentEvtFilterVal) evtFilterSelect.value = currentEvtFilterVal;
        if (blDeviceSelect && currentBlVal) blDeviceSelect.value = currentBlVal;
        if (activitySelect && currentActVal) activitySelect.value = currentActVal;
        if (otpSelect && currentOtpVal) otpSelect.value = currentOtpVal;
        if (patchSelect && currentPatchVal) patchSelect.value = currentPatchVal;

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
        renderPatchStatus();

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
    } catch (e) {
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
    } catch (e) {
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

// ── Activity View ─────────────────────────────────────────────────────────

let activityTotalPages = 1;

function formatIdle(sec) {
    if (sec == null) return '—';
    const s = Math.max(0, parseInt(sec, 10));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    if (m < 60) return `${m}m ${r}s`;
    const h = Math.floor(m / 60);
    const mm = m % 60;
    return `${h}h ${mm}m`;
}

let statusRingInstance = null;
let appUsageBarInstance = null;

function renderStatusRing(active, idle) {
    const ctx = document.getElementById('statusRingChart');
    if (!ctx) return;
    if (statusRingInstance) statusRingInstance.destroy();

    const total = active + idle;
    const activePerc = total > 0 ? ((active / total) * 100).toFixed(0) : 0;
    if (document.getElementById('activePercentageText')) {
        document.getElementById('activePercentageText').textContent = activePerc + '%';
    }

    statusRingInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Active', 'Idle'],
            datasets: [{
                data: [active, idle],
                backgroundColor: ['#4633ff', 'rgba(0,0,0,0.05)'],
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '80%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(c) {
                            return `${c.label}: ${formatIdle(c.raw)}`;
                        }
                    }
                }
            }
        }
    });
}

function renderAppUsageBarChart(labelMap) {
    const ctx = document.getElementById('appUsageBarChart');
    if (!ctx) return;
    if (appUsageBarInstance) appUsageBarInstance.destroy();

    const sorted = Object.entries(labelMap)
        .filter(([k]) => k.toLowerCase() !== 'idle')
        .sort((a,b) => b[1] - a[1])
        .slice(0, 8);

    const labels = sorted.map(x => x[0]);
    const data = sorted.map(x => x[1]);

    appUsageBarInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Usage Time',
                data: data,
                backgroundColor: 'rgba(70, 51, 255, 0.8)',
                borderRadius: 5,
                borderWidth: 0,
                barThickness: 15
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(c) {
                            return `Focus Time: ${formatIdle(c.raw)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: false,
                    grid: { display: false }
                },
                y: {
                    grid: { display: false },
                    ticks: {
                        color: 'var(--text-3)',
                        font: { size: 11 }
                    }
                }
            }
        }
    });
}

async function loadActivity(page = 1) {
    try {
        activityPage = page;
        let url = `/api/v1/activity?page=${activityPage}&limit=${activityLimit}`;
        const device = $('activityDevice')?.value;
        const search = $('activitySearch')?.value;
        const fromVal = $('activityFrom')?.value;
        const toVal = $('activityTo')?.value;

        const toIso = (v) => {
            if (!v) return null;
            const d = new Date(v);
            return isNaN(d.getTime()) ? null : d.toISOString();
        };

        if (device) url += `&device_id=${encodeURIComponent(device)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        const df = toIso(fromVal);
        const dt = toIso(toVal);
        if (df) url += `&date_from=${encodeURIComponent(df)}`;
        if (dt) url += `&date_to=${encodeURIComponent(dt)}`;

        const data = await api('GET', url);
        const items = data.items || [];
        const total = data.total || 0;

        // ── Fetch Analytics Stats & Render Chart ──
        let statsUrl = `/api/v1/activity/stats?`;
        if (device) statsUrl += `device_id=${encodeURIComponent(device)}&`;
        
        let statsDf = df;
        if (!statsDf) {
            const yesterday = new Date();
            yesterday.setHours(yesterday.getHours() - 24);
            statsDf = yesterday.toISOString();
        }
        statsUrl += `date_from=${encodeURIComponent(statsDf)}&`;
        if (dt) statsUrl += `date_to=${encodeURIComponent(dt)}&`;
        
        try {
            const stats = await api('GET', statsUrl);
            const idleSec = stats.total_idle_seconds || 0;
            const deviceCount = stats.device_count || 1;

            let activeSec = 0;
            const labelMap = stats.process_distribution || {};

            for (const [proc, sec] of Object.entries(labelMap)) {
                if (proc.toLowerCase() !== 'idle') {
                    activeSec += sec;
                }
            }

            if ($('statIdleTime')) $('statIdleTime').textContent = formatIdle(idleSec);
            if ($('statActiveTime')) $('statActiveTime').textContent = formatIdle(activeSec);

            if ($('activityDeviceCount')) {
                if (deviceCount > 1) {
                    $('activityDeviceCount').textContent = `${deviceCount} Devices`;
                    $('activityDeviceCount').style.display = 'inline-block';
                } else {
                    $('activityDeviceCount').style.display = 'none';
                }
            }

            renderStatusRing(activeSec, idleSec);
            renderAppUsageBarChart(labelMap);

            // ── Populating Detailed Breakdown Table ──
            const detailsBody = document.getElementById('activityDetailsBody');
            if (detailsBody) {
                const groupedApps = Object.entries(labelMap)
                    .filter(([p]) => p.toLowerCase() !== 'idle')
                    .sort((a,b) => b[1] - a[1]);

                if (groupedApps.length === 0) {
                    detailsBody.innerHTML = '<tr><td colspan="3"><div class="empty-state">No app activity recorded.</div></td></tr>';
                } else {
                    const windowMap = {};
                    items.forEach(it => {
                        const p = it.process_name || 'Unknown';
                        if (!windowMap[p]) windowMap[p] = new Set();
                        if (it.window_title) windowMap[p].add(it.window_title);
                    });

                    detailsBody.innerHTML = groupedApps.map(([proc, sec]) => {
                        const titles = Array.from(windowMap[proc] || []).slice(0, 3).join(', ');
                        const titlesDisp = titles ? `<small style="color:var(--text-3)">${escapeHtml(titles)}</small>` : '—';
                        return `<tr>
                            <td><strong>${escapeHtml(proc)}</strong></td>
                            <td>${titlesDisp}</td>
                            <td><span class="badge badge-info">${formatIdle(sec)}</span></td>
                        </tr>`;
                    }).join('');
                }
            }
        } catch (e) {
            console.error("Stats fetching failed", e);
        }
        const limit = data.limit || activityLimit;
        const pageResp = data.page || activityPage;

        activityTotalPages = Math.max(1, Math.ceil(total / limit));
        activityPage = pageResp;

        if ($('activityTotal')) $('activityTotal').textContent = `${total} events`;
        if ($('activityPageNumber')) $('activityPageNumber').textContent = String(activityPage);

        const tbody = $('activityTableBody');
        if (!tbody) return;

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><span class="ei">📭</span>No activity yet</div></td></tr>`;
        } else {
            tbody.innerHTML = items.map(i => {
                const idle = formatIdle(i.idle_seconds);
                const inputTxt = `${i.click_count || 0} clicks / ${i.keypress_count || 0} keys`;
                const deviceLabel = (() => {
                    const d = (_deviceCache || []).find(x => x.id === i.device_id);
                    return d ? d.hostname : (i.device_id || '');
                })();
                return `<tr>
                    <td>${formatDate(i.timestamp)}</td>
                    <td>${escapeHtml(deviceLabel)}</td>
                    <td>${escapeHtml(i.window_title || '—')}</td>
                    <td>${escapeHtml(i.process_name || '—')}</td>
                    <td>${idle}</td>
                    <td>${inputTxt}</td>
                </tr>`;
            }).join('');
        }

        if ($('activityPageInfo')) {
            const startIdx = total === 0 ? 0 : ((activityPage - 1) * limit) + 1;
            const endIdx = Math.min(activityPage * limit, total);
            $('activityPageInfo').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }

        if ($('btnActivityPrev')) $('btnActivityPrev').disabled = activityPage <= 1;
        if ($('btnActivityNext')) $('btnActivityNext').disabled = activityPage >= activityTotalPages;

        // ── Auto-Refresh for Live Enterprise Monitoring ──
        if (!window._activityRefreshInterval) {
            window._activityRefreshInterval = setInterval(() => {
                const view = document.getElementById('view-activity');
                if (view && view.style.display !== 'none') {
                    // Refresh current page without resetting pagination
                    loadActivity(activityPage); 
                }
            }, 30000); // 30-second live refresh
        }
    } catch (err) {
        const tbody = $('activityTableBody');
        if (tbody) tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><span class="ei">⚠️</span>${err.message || 'Failed to load activity'}</div></td></tr>`;
    }
}

function activityPrevPage() {
    if (activityPage > 1) loadActivity(activityPage - 1);
}
function activityNextPage() {
    if (activityPage < activityTotalPages) loadActivity(activityPage + 1);
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
        if (device.is_uninstalled) {
            badgeEl.innerHTML = `<span class="badge" style="background:rgba(150,150,150,0.15);color:#aaa;border:1px solid rgba(150,150,150,0.3);"><span class="badge-dot" style="background:#aaa"></span>Uninstalled</span>`;
        } else {
            const diff = Date.now() - new Date(device.last_seen);
            const isOn = device.last_seen && diff < 30 * 1000 && diff > -60 * 1000;
            badgeEl.innerHTML = isOn
                ? `<span class="badge badge-completed"><span class="badge-dot"></span>Online</span>`
                : `<span class="badge badge-failed"><span class="badge-dot"></span>Offline</span>`;
        }
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

// ── Installed Software ────────────────────────────────────────────────────

function openSoftwareModal() {
    if (!selectedDeviceId) {
        toast('Select a device first.', 'error');
        return;
    }
    const device = _deviceCache.find(d => d.id == selectedDeviceId);
    document.getElementById('swDeviceName').textContent = device ? device.hostname : selectedDeviceId;
    document.getElementById('softwareModal').classList.add('show');
    loadSoftwareInventory();
}

function closeSoftwareModal(e) {
    const modal = document.getElementById('softwareModal');
    if (e && e.target !== modal) {
        modal.classList.remove('show');
        return;
    }
    modal.classList.remove('show');
}

async function loadSoftwareInventory() {
    if (!selectedDeviceId) {
        toast('Select a device first.', 'error');
        return;
    }
    const search = ($('softwareSearch')?.value || '').trim();
    const table = $('softwareTable');
    if (table) {
        table.innerHTML = '<div class="empty-state"><span class="ei">⏳</span>Loading installed software…</div>';
    }
    try {
        const path = search
            ? `/api/v1/device/${selectedDeviceId}/software?search=${encodeURIComponent(search)}`
            : `/api/v1/device/${selectedDeviceId}/software`;
        const res = await api('GET', path);
        renderSoftwareTable(res.items || []);
    } catch (err) {
        if (table) {
            table.innerHTML = `<div class="empty-state"><span class="ei">⚠️</span>${err.message || 'Failed to load software'}</div>`;
        }
    }
}

function renderSoftwareTable(items) {
    const table = $('softwareTable');
    const count = $('swCount');
    if (count) count.textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
    if (!table) return;

    if (!items || items.length === 0) {
        table.innerHTML = '<div class="empty-state"><span class="ei">🧹</span>No software reported yet.</div>';
        return;
    }

    const canUninstall = _userRole === 'admin';
    let html = `
        <div class="software-row header">
            <div>Name</div>
            <div>Version</div>
            <div>Publisher</div>
            <div>Installed</div>
            <div style="text-align:right;">Actions</div>
        </div>`;

    items.forEach(item => {
        html += `
        <div class="software-row">
            <div>
                <div class="software-name">${escapeHtml(item.name)}</div>
            </div>
            <div>${escapeHtml(item.version || '—')}</div>
            <div>${escapeHtml(item.publisher || '—')}</div>
            <div>${escapeHtml(item.install_date || '—')}</div>
            <div class="software-actions">
                <button class="btn btn-danger btn-sm btn-uninstall"
                    data-name="${escapeAttr(item.name)}"
                    data-uninstall="${escapeAttr(item.uninstall_string || '')}"
                    ${!canUninstall ? 'disabled title="Admin role required"' : ''}>
                    🗑️ Uninstall
                </button>
            </div>
        </div>`;
    });

    table.innerHTML = html;

    if (canUninstall) {
        table.querySelectorAll('.btn-uninstall').forEach(btn => {
            btn.addEventListener('click', () => {
                const name = btn.getAttribute('data-name') || '';
                const uninstall = btn.getAttribute('data-uninstall') || '';
                queueUninstallSoftware({ name, uninstall_string: uninstall });
            });
        });
    }
}

async function queueUninstallSoftware(item) {
    if (_userRole !== 'admin') {
        toast('Admin role required to uninstall software.', 'error');
        return;
    }
    if (!selectedDeviceId) {
        toast('Select a device first.', 'error');
        return;
    }
    if (!item.uninstall_string) {
        toast('No uninstall command is available for this app.', 'error');
        return;
    }
    const confirmed = confirm(`Queue uninstall of \"${item.name}\" on this device?`);
    if (!confirmed) return;

    try {
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'uninstall_software',
            payload: JSON.stringify({
                name: item.name,
                uninstall_string: item.uninstall_string,
            })
        });
        toast(`Uninstall queued for \"${item.name}\"`, 'success');
        if (typeof loadHistory === 'function') loadHistory();
    } catch (err) {
        toast(err.message || 'Failed to queue uninstall', 'error');
    }
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

        const infoStr = cachedDevice.system_info;
        const info = (typeof infoStr === 'string' && infoStr !== 'null') ? JSON.parse(infoStr) : (infoStr || {});
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
            toast(`Requesting live BitLocker key from agent...`, 'info');
            try {
                const res = await api('POST', '/send_command', {
                    device_id: targetId,
                    action: 'get_bitlocker_key',
                    payload: driveLetter
                });
                const cmdId = res.command_id;
                toast(`Command sent! Waiting for agent to respond...`, 'info');
                
                let attempts = 0;
                const maxAttempts = 20; // up to 30 seconds
                const pollTimer = setInterval(async () => {
                    attempts++;
                    try {
                        const hist = await api('GET', `/commands/history?device_id=${encodeURIComponent(targetId)}&action=get_bitlocker_key&limit=5`);
                        if (hist && hist.commands) {
                            const cmd = hist.commands.find(c => c.id === cmdId);
                            if (cmd) {
                                if (cmd.status === 'completed' || cmd.status === 'failed') {
                                    clearInterval(pollTimer);
                                    if (cmd.status === 'completed') {
                                        toast(`BitLocker key retrieved successfully!`, 'success');
                                        document.getElementById('bkModalDevice').textContent = cachedDevice.hostname;
                                        document.getElementById('bkModalDrive').textContent = driveLetter;
                                        document.getElementById('bkModalKey').textContent = cmd.result || 'Unknown result';
                                        document.getElementById('bitlockerKeyModal').classList.add('show');
                                    } else {
                                        toast(`Agent failed to retrieve key: ${cmd.result}`, 'error');
                                    }
                                    return;
                                }
                            }
                        }
                    } catch(e) { console.error('Poll error', e); }
                    
                    if (attempts >= maxAttempts) {
                        clearInterval(pollTimer);
                        toast(`Timed out waiting for agent. Please check Command History later.`, 'warning');
                    }
                }, 1500);

            } catch (err) {
                toast(`Failed to send request: ${err.message}`, 'error');
            }
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

// ── Maintenance / Patch Management ─────────────────────────────────────────

async function generateOtpForDevice() {
    const deviceId = $('otpDeviceSelect')?.value;
    if (!deviceId) return;

    const btn = $('btnGenerateOtp');
    const original = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
        const res = await api('POST', '/generate-uninstall-password', { device_id: deviceId });
        const exp = res.expires_at ? new Date(res.expires_at).toLocaleTimeString() : '5 minutes';
        if ($('otpResultText')) $('otpResultText').textContent = `OTP: ${res.otp} (expires ${exp})`;
        toast('OTP generated', 'success');
    } catch (e) {
        toast(e.message || 'Failed to generate OTP', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}

function renderPatchStatus() {
    const panel = $('patchStatusBox');
    if (!panel) return;
    const select = $('patchDeviceSelect');
    const deviceId = (select && select.value) || selectedDeviceId;
    if (!deviceId) {
        panel.innerHTML = '<div class="empty-state" style="padding:10px;">Select a device to view patch status.</div>';
        return;
    }
    const device = (_deviceCache || []).find(d => d.id == deviceId);
    if (!device) {
        panel.innerHTML = '<div class="empty-state" style="padding:10px;">Device not found.</div>';
        return;
    }

    const version = device.agent_version || 'Not reported';
    const lastCheck = device.last_version_check ? formatDate(device.last_version_check) : '—';
    let badge = '<span class="badge badge-pending"><span class="badge-dot"></span>Unknown</span>';
    if (_latestAgentVersion && device.agent_version) {
        const cmp = semverCompare(_latestAgentVersion, device.agent_version);
        if (cmp <= 0) {
            badge = '<span class="badge badge-completed"><span class="badge-dot"></span>Up to date</span>';
        } else {
            badge = '<span class="badge badge-failed"><span class="badge-dot"></span>Update available</span>';
        }
    }

    panel.innerHTML = `
        <div class="sysinfo-row"><span>Agent version</span><strong>${version}</strong></div>
        <div class="sysinfo-row"><span>Last version check</span><strong>${lastCheck}</strong></div>
        <div class="sysinfo-row"><span>Status</span>${badge}</div>
        <div class="sysinfo-row"><span>Latest release</span><strong>${_latestAgentVersion || '—'}</strong></div>
    `;
}

function renderVersionTable(items = []) {
    if ($('latestVersionLabel')) $('latestVersionLabel').textContent = _latestAgentVersion || '—';
    const tbody = $('versionTableBody');
    if (!tbody) return;
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No agent builds uploaded yet.</div></td></tr>';
        return;
    }
    const toMb = (b) => b ? `${(b / 1024 / 1024).toFixed(1)} MB` : '—';
    tbody.innerHTML = items.map(v => `
        <tr>
            <td>${v.version}</td>
            <td>${v.platform || 'windows'}</td>
            <td>${formatDate(v.created_at)}</td>
            <td>${toMb(v.file_size)}</td>
            <td>${v.is_active ? 'Active' : 'Archived'}</td>
        </tr>
    `).join('');
}

async function loadAgentVersions(force = false) {
    const now = Date.now();
    if (!force && now - _lastVersionFetch < 60000) return;
    try {
        const res = await api('GET', '/api/v1/admin/agent-versions');
        _lastVersionFetch = now;
        const items = res.items || [];
        _latestAgentVersion = items.length ? items[0].version : null;
        renderVersionTable(items);
        renderPatchStatus();
    } catch (e) {
        console.error('loadAgentVersions error:', e);
    }
}

async function uploadAgentVersion(evt) {
    if (evt) evt.preventDefault();
    const version = $('uploadVersionInput')?.value?.trim();
    const file = $('uploadFileInput')?.files?.[0];
    const notes = $('uploadNotesInput')?.value || '';
    if (!version || !file) {
        toast('Version and binary are required', 'error');
        return;
    }
    const btn = $('btnUploadVersion');
    const original = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Uploading…'; }
        const fd = new FormData();
        fd.append('version', version);
        fd.append('file', file);
        if (notes) fd.append('release_notes', notes);
        const token = localStorage.getItem('token');
        const res = await fetch(`${API_BASE}/api/v1/admin/agent-version`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: fd,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Upload failed');
        }
        toast('Agent update uploaded', 'success');
        $('uploadVersionInput').value = '';
        $('uploadFileInput').value = '';
        $('uploadNotesInput').value = '';
        await loadAgentVersions(true);
    } catch (e) {
        toast(e.message || 'Upload failed', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
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
    const activityView = document.getElementById('view-activity');
    if (activityView && activityView.classList.contains('active')) {
        await loadActivity(activityPage);
    }
    const maintenanceView = document.getElementById('view-maintenance');
    if (maintenanceView && maintenanceView.classList.contains('active')) {
        await loadAgentVersions();
        renderPatchStatus();
    }
}

// Initial load
loadUserRole();  // Apply RBAC immediately
pollAll();

// Auto-refresh every 5 seconds
pollInterval = setInterval(pollAll, 5000);


// ── Protected Uninstall OTP ──────────────────────────────────────────────

let _otpCountdownTimer = null;
let _currentOtpCode = '';

async function generateOtpForDevice() {
    const deviceId = $('otpDeviceSelect')?.value;
    if (!deviceId) { toast('Please select a target device', 'error'); return; }

    const btn = $('btnGenerateOtp');
    const original = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
        const res = await api('POST', '/generate-uninstall-password', { device_id: deviceId });
        _currentOtpCode = res.otp || '';

        const device = _deviceCache.find(d => d.id == deviceId);
        const lbl = $('otpDeviceLabel');
        if (lbl) lbl.textContent = device ? ('Device: ' + device.hostname + '  (' + device.ip_address + ')') : ('Device ID: ' + deviceId);

        const display = $('otpCodeDisplay');
        if (display) { display.textContent = _currentOtpCode; display.style.color = 'var(--accent)'; }

        clearInterval(_otpCountdownTimer);
        let secsLeft = 5 * 60;
        const tick = () => {
            const el = $('otpCountdown');
            if (!el) return;
            const m = Math.floor(secsLeft / 60);
            const s = String(secsLeft % 60).padStart(2, '0');
            el.textContent = m + ':' + s;
            el.style.color = secsLeft <= 60 ? 'var(--red)' : 'var(--text)';
            if (secsLeft <= 0) {
                clearInterval(_otpCountdownTimer);
                el.textContent = 'Expired';
                el.style.color = 'var(--red)';
                if (display) { display.textContent = '------'; display.style.color = 'var(--text-3)'; }
            }
            secsLeft--;
        };
        tick();
        _otpCountdownTimer = setInterval(tick, 1000);

        const modal = $('otpModal');
        if (modal) modal.classList.add('show');

        toast('OTP generated for ' + (device ? device.hostname : deviceId), 'success');
    } catch (e) {
        toast(e.message || 'Failed to generate OTP', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}

function closeOtpModal() {
    const modal = $('otpModal');
    if (modal) modal.classList.remove('show');
    clearInterval(_otpCountdownTimer);
}

function copyOtp() {
    navigator.clipboard.writeText(_currentOtpCode).then(() => {
        toast('OTP copied to clipboard', 'success');
    }).catch(() => {
        toast('Copy failed. OTP: ' + _currentOtpCode, 'info');
    });
}

// ── Delete Uninstalled Device from Portal ────────────────────────────────────

async function deleteDeviceFromPortal(deviceId, hostname) {
    if (!confirm(`Permanently delete "${hostname}" from the portal?\n\nThis cannot be undone. The device record, command history, and event logs will all be removed.`)) return;
    try {
        await api('DELETE', `/devices/${deviceId}`);
        toast(`Device "${hostname}" has been permanently removed.`, 'success');
        await loadDevices();
    } catch (e) {
        toast(`Failed to delete: ${e.message}`, 'error');
    }
}
