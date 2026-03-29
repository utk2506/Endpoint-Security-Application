/**
 * features/sysInfo.js
 * System Info modal — open, close, render.
 */

import { $, escapeHtml, escapeAttr, toast } from '../core/utils.js';
import { selectedDeviceId, _deviceCache } from './devices.js';

export function openSysInfoModal() {
    const deviceId = selectedDeviceId;
    if (!deviceId) { toast('Select a device first.', 'error'); return; }

    const device   = _deviceCache.find(d => d.id == deviceId);
    const hostname = device ? device.hostname : deviceId;
    document.getElementById('sysInfoDeviceName').textContent = hostname;

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

export function closeSysInfoModal(e) {
    if (e && e.target !== document.getElementById('sysInfoModal')) return;
    document.getElementById('sysInfoModal').classList.remove('show');
}

export function renderSysInfo(container, info, deviceId) {
    // info may be a JSON string or already an object
    if (typeof info === 'string' && info !== 'null') {
        try { info = JSON.parse(info); } catch { info = {}; }
    }
    if (!info || info === 'null') info = {};

    const pct = (v, total) => {
        const p     = total > 0 ? Math.min(100, Math.round((v / total) * 100)) : 0;
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

    const disks    = Array.isArray(info.disks) ? info.disks : (info.disks ? [info.disks] : []);
    const disksHtml = disks.map(d => {
        const blStatus   = d.bitlocker  || '0% (Off)';
        const convStatus = d.bl_status  || 'Ready';
        const isEncrypted= blStatus.toLowerCase().includes('on') || (blStatus.includes('%') && !blStatus.startsWith('0%'));
        const blColor    = isEncrypted ? 'var(--success)' : 'var(--text-secondary)';
        const blIcon     = isEncrypted ? '🔒' : '🔓';
        const keyBtn     = isEncrypted
            ? `<button class="btn btn-sm" style="margin-top:10px; width:100%; justify-content:center; background:var(--bg); border:1px solid var(--accent); color:var(--accent); font-weight:700;"
                     onclick="getBitLockerKey('${deviceId}', '${escapeAttr(d.drive)}')">🔑 Get Recovery Key</button>`
            : '';
        return `
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">💾 Storage — ${d.drive}</div>
            ${row('Total', `${d.size_gb} GB`)}
            ${row('Free',  `${d.free_gb} GB`)}
            ${row('BitLocker', `<span style="color:${blColor}; font-weight:600;">${blIcon} ${blStatus}</span>`)}
            ${row('Conv. Status', `<small style="color:var(--text-muted)">${convStatus}</small>`)}
            ${keyBtn}
            ${pct(d.size_gb - d.free_gb, d.size_gb)}
        </div>`;
    }).join('');

    const nics    = Array.isArray(info.network) ? info.network : (info.network ? [info.network] : []);
    const nicsHtml = nics.map(n => `
        <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.04); padding-bottom: 6px;">
            <div style="font-size:11px; color:var(--text-secondary); margin-bottom:4px;">${n.description || 'Adapter'}</div>
            ${row('IPv4 Address', n.ip  || '—')}
            ${row('MAC Address',  n.mac || '—')}
        </div>`).join('');

    container.innerHTML = `<div class="sysinfo-grid">
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🖥️ System</div>
            ${row('Hostname',       info.hostname)}
            ${row('Logged-in User', info.logged_user)}
            ${row('Manufacturer',   info.manufacturer)}
            ${row('Model',          info.model)}
            ${row('Serial',         info.serial_number)}
            ${row('BIOS',           info.bios_version)}
            ${row('Uptime',         info.uptime)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">⚙️ OS</div>
            ${row('OS Name',       info.os_name)}
            ${row('Version',       info.os_version)}
            ${row('Architecture',  info.os_arch)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🧠 CPU</div>
            ${row('Processor',     info.cpu_name)}
            ${row('Cores',         info.cpu_cores)}
            ${row('Current Load',  info.cpu_load_pct != null ? `${info.cpu_load_pct}%` : '—')}
            ${pct(info.cpu_load_pct || 0, 100)}
        </div>
        <div class="sysinfo-card">
            <div class="sysinfo-card-title">🗄️ RAM</div>
            ${row('Total RAM', `${info.ram_total_gb} GB`)}
            ${row('Used RAM',  `${ramUsed.toFixed(2)} GB`)}
            ${row('Free RAM',  `${(info.ram_free_gb || 0).toFixed(2)} GB`)}
            ${pct(ramUsed, info.ram_total_gb || 1)}
        </div>
        ${disksHtml}
        <div class="sysinfo-card full-width">
            <div class="sysinfo-card-title">🌐 Network</div>
            ${nicsHtml || row('Status', 'No active adapters found')}
        </div>
    </div>`;
}
