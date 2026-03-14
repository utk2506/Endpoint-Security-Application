/**
 * Admin Control System — Dashboard Logic
 * Handles all API communication, UI updates, and polling.
 */

const API_BASE = window.location.origin;
const WS_BASE = window.location.origin.replace('http', 'ws');
let selectedDeviceId = null;
let pollInterval = null;

// Terminal State
let term = null;
let terminalSocket = null;

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
        const filterSelect = $('filterDevice');
        const currentVal = select.value;
        const currentFilterVal = filterSelect ? filterSelect.value : '';
        
        select.innerHTML = '<option value="">— Select a device —</option>';
        if (filterSelect) {
            filterSelect.innerHTML = '<option value="">All Devices</option>';
        }

        const now = new Date();
        devices.forEach(d => {
            const lastSeen = new Date(d.last_seen);
            const isOnline = (now - lastSeen) < 15000; // 15 seconds threshold
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
        });

        // Restore selection
        if (currentVal) select.value = currentVal;
        if (currentFilterVal && filterSelect) filterSelect.value = currentFilterVal;

        $('statDevices').textContent = devices.length;
    } catch {
        setConnected(false);
    }
}

// ── Device selection ───────────────────────────────────────────────────────
// (...) unchanged code up to Command History


$('deviceSelect')?.addEventListener('change', function () {
    selectedDeviceId = this.value ? this.value : null;
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
        const total = data.total || 0;
        const page = data.page || 1;
        const limit = data.limit || 20;

        const tbody = $('historyTableBody');

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7">
                <div class="empty-state"><span class="icon">📭</span>No commands found</div>
            </td></tr>`;
            $('statCommands').textContent = '0';
            // Update Pagination UI
            if ($('pageInfoText')) $('pageInfoText').textContent = '0 results';
            if ($('pageIndicator')) $('pageIndicator').textContent = '1';
            if ($('btnPrevPage')) $('btnPrevPage').disabled = true;
            if ($('btnNextPage')) $('btnNextPage').disabled = true;
            return;
        }

        const completedCount = history.filter(c => c.status === 'completed').length;
        $('statCommands').textContent = completedCount; // NOTE: This is now just the count on THIS page

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
            const actionIcons = { grant: '✅', revoke: '🚫', check: '🔍', shell: '💻' };
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
