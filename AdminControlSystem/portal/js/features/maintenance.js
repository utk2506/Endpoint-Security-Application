/**
 * features/maintenance.js
 * OTP generation + countdown modal, patch status, agent version upload.
 */

import { api, API_BASE } from '../core/api.js';
import { $, formatDate, semverCompare, toast } from '../core/utils.js';
import { selectedDeviceId, _deviceCache } from './devices.js';

// ── Shared version state ──────────────────────────────────────────────────
export let _latestAgentVersion = null;
let _lastVersionFetch = 0;

// ── OTP ──────────────────────────────────────────────────────────────────
let _otpCountdownTimer = null;
let _currentOtpCode    = '';

export async function generateOtpForDevice() {
    const deviceId = $('otpDeviceSelect')?.value;
    if (!deviceId) { toast('Please select a target device', 'error'); return; }

    const btn      = $('btnGenerateOtp');
    const original = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
        const res = await api('POST', '/generate-uninstall-password', { device_id: deviceId });
        _currentOtpCode = res.otp || '';

        const device = _deviceCache.find(d => d.id == deviceId);
        const lbl    = $('otpDeviceLabel');
        if (lbl) lbl.textContent = device
            ? `Device: ${device.hostname}  (${device.ip_address})`
            : `Device ID: ${deviceId}`;

        const display = $('otpCodeDisplay');
        if (display) { display.textContent = _currentOtpCode; display.style.color = 'var(--accent)'; }

        clearInterval(_otpCountdownTimer);
        let secsLeft = 5 * 60;
        const tick = () => {
            const el = $('otpCountdown');
            if (!el) return;
            const m = Math.floor(secsLeft / 60);
            const s = String(secsLeft % 60).padStart(2, '0');
            el.textContent = `${m}:${s}`;
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

        toast(`OTP generated for ${device ? device.hostname : deviceId}`, 'success');
    } catch (e) {
        toast(e.message || 'Failed to generate OTP', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}

export function closeOtpModal() {
    const modal = $('otpModal');
    if (modal) modal.classList.remove('show');
    clearInterval(_otpCountdownTimer);
}

export function copyOtp() {
    navigator.clipboard.writeText(_currentOtpCode).then(() => {
        toast('OTP copied to clipboard', 'success');
    }).catch(() => {
        toast(`Copy failed. OTP: ${_currentOtpCode}`, 'info');
    });
}

// ── Patch Status ──────────────────────────────────────────────────────────
export function renderPatchStatus() {
    const panel  = $('patchStatusBox');
    if (!panel) return;
    const select   = $('patchDeviceSelect');
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

    const version   = device.agent_version || 'Not reported';
    const lastCheck = device.last_version_check ? formatDate(device.last_version_check) : '—';
    let badge = '<span class="badge badge-pending"><span class="badge-dot"></span>Unknown</span>';
    if (_latestAgentVersion && device.agent_version) {
        const cmp = semverCompare(_latestAgentVersion, device.agent_version);
        badge = cmp <= 0
            ? '<span class="badge badge-completed"><span class="badge-dot"></span>Up to date</span>'
            : '<span class="badge badge-failed"><span class="badge-dot"></span>Update available</span>';
    }

    panel.innerHTML = `
        <div class="sysinfo-row"><span>Agent version</span><strong>${version}</strong></div>
        <div class="sysinfo-row"><span>Last version check</span><strong>${lastCheck}</strong></div>
        <div class="sysinfo-row"><span>Status</span>${badge}</div>
        <div class="sysinfo-row"><span>Latest release</span><strong>${_latestAgentVersion || '—'}</strong></div>
    `;
}

export function renderVersionTable(items = []) {
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

export async function loadAgentVersions(force = false) {
    const now = Date.now();
    if (!force && now - _lastVersionFetch < 60000) return;
    try {
        const res   = await api('GET', '/api/v1/admin/agent-versions');
        _lastVersionFetch      = now;
        const items = res.items || [];
        _latestAgentVersion    = items.length ? items[0].version : null;
        renderVersionTable(items);
        renderPatchStatus();
    } catch (e) {
        console.error('loadAgentVersions error:', e);
    }
}

export async function uploadAgentVersion(evt) {
    if (evt) evt.preventDefault();
    const version = $('uploadVersionInput')?.value?.trim();
    const file    = $('uploadFileInput')?.files?.[0];
    const notes   = $('uploadNotesInput')?.value || '';
    if (!version || !file) { toast('Version and binary are required', 'error'); return; }

    const btn      = $('btnUploadVersion');
    const original = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Uploading…'; }
        const fd = new FormData();
        fd.append('version', version);
        fd.append('file', file);
        if (notes) fd.append('release_notes', notes);
        const token = localStorage.getItem('token');
        const res   = await fetch(`${API_BASE}/api/v1/admin/agent-version`, {
            method:  'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body:    fd,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Upload failed');
        }
        toast('Agent update uploaded', 'success');
        $('uploadVersionInput').value = '';
        $('uploadFileInput').value    = '';
        $('uploadNotesInput').value   = '';
        await loadAgentVersions(true);
    } catch (e) {
        toast(e.message || 'Upload failed', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}
