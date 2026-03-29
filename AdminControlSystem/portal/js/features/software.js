/**
 * features/software.js
 * Installed software modal with search and uninstall queuing.
 */

import { api } from '../core/api.js';
import { $, escapeHtml, escapeAttr, toast } from '../core/utils.js';
import { selectedDeviceId, _deviceCache } from './devices.js';
import { getRole } from '../core/auth.js';

export function openSoftwareModal() {
    if (!selectedDeviceId) { toast('Select a device first.', 'error'); return; }
    const device = _deviceCache.find(d => d.id == selectedDeviceId);
    document.getElementById('swDeviceName').textContent = device ? device.hostname : selectedDeviceId;
    document.getElementById('softwareModal').classList.add('show');
    loadSoftwareInventory();
}

export function closeSoftwareModal(e) {
    const modal = document.getElementById('softwareModal');
    if (e && e.target !== modal) { modal.classList.remove('show'); return; }
    modal.classList.remove('show');
}

export async function loadSoftwareInventory() {
    if (!selectedDeviceId) { toast('Select a device first.', 'error'); return; }
    const search = ($('softwareSearch')?.value || '').trim();
    const table  = $('softwareTable');
    if (table) table.innerHTML = '<div class="empty-state"><span class="ei">⏳</span>Loading installed software…</div>';

    try {
        const path = search
            ? `/api/v1/device/${selectedDeviceId}/software?search=${encodeURIComponent(search)}`
            : `/api/v1/device/${selectedDeviceId}/software`;
        const res = await api('GET', path);
        renderSoftwareTable(res.items || []);
    } catch (err) {
        if (table) table.innerHTML = `<div class="empty-state"><span class="ei">⚠️</span>${err.message || 'Failed to load software'}</div>`;
    }
}

export function renderSoftwareTable(items) {
    const table = $('softwareTable');
    const count = $('swCount');
    if (count) count.textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
    if (!table) return;

    if (!items || items.length === 0) {
        table.innerHTML = '<div class="empty-state"><span class="ei">🧹</span>No software reported yet.</div>';
        return;
    }

    const canUninstall = getRole() === 'admin';
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
            <div><div class="software-name">${escapeHtml(item.name)}</div></div>
            <div>${escapeHtml(item.version   || '—')}</div>
            <div>${escapeHtml(item.publisher  || '—')}</div>
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
                const name      = btn.getAttribute('data-name')      || '';
                const uninstall = btn.getAttribute('data-uninstall') || '';
                queueUninstallSoftware({ name, uninstall_string: uninstall });
            });
        });
    }
}

export async function queueUninstallSoftware(item) {
    if (getRole() !== 'admin') { toast('Admin role required to uninstall software.', 'error'); return; }
    if (!selectedDeviceId)     { toast('Select a device first.', 'error'); return; }
    if (!item.uninstall_string){ toast('No uninstall command is available for this app.', 'error'); return; }
    if (!confirm(`Queue uninstall of "${item.name}" on this device?`)) return;

    try {
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action:    'uninstall_software',
            payload:   JSON.stringify({ name: item.name, uninstall_string: item.uninstall_string }),
        });
        toast(`Uninstall queued for "${item.name}"`, 'success');
        import('./history.js').then(m => m.loadHistory());
    } catch (err) {
        toast(err.message || 'Failed to queue uninstall', 'error');
    }
}
