/**
 * features/notifications.js
 * Notification campaigns — create, list, cancel; notify schedule toggle.
 */

import { api } from '../core/api.js';
import { $, formatDate, escapeHtml, toast } from '../core/utils.js';
import { _deviceCache } from './devices.js';

export function toggleNotifySchedule() {
    const isRecurring = $('notifyScheduleType')?.value === 'recurring';
    const opts = $('notifyRecurringOptions');
    if (opts) opts.style.display = isRecurring ? 'block' : 'none';
}

export async function sendNotification() {
    const notifyCheckboxes = document.querySelectorAll('.notify-target-device:checked');
    const notifyDeviceIds  = Array.from(notifyCheckboxes).map(c => c.value);

    if (notifyDeviceIds.length === 0) { toast('Select at least one target device', 'error'); return; }

    const message = $('notifyMessage')?.value.trim();
    if (!message) { toast('Enter a message', 'error'); return; }

    const targetUsers  = ['All'];
    const isRecurring  = $('notifyScheduleType')?.value === 'recurring';
    const stInput      = $('notifyStartTime')?.value;
    const etInput      = $('notifyEndTime')?.value;
    const interval     = parseInt($('notifyInterval')?.value, 10);

    const payload = {
        device_ids:   notifyDeviceIds,
        message,
        target_users: targetUsers,
        is_recurring: isRecurring,
    };

    if (isRecurring) {
        if (!etInput) { toast('End Time is required for recurring campaigns', 'error'); return; }
        if (isNaN(interval) || interval < 1) { toast('Invalid interval', 'error'); return; }
        let st = stInput ? new Date(stInput) : new Date();
        let et = new Date(etInput);
        payload.start_time        = st.toISOString();
        payload.end_time          = et.toISOString();
        payload.interval_minutes  = interval;
    }

    try {
        await api('POST', '/api/v1/notifications', payload);
        toast(isRecurring ? 'Recurring notification campaign created!' : 'Notification command queued!', 'success');
        if ($('notifyMessage')) $('notifyMessage').value = '';
        if (isRecurring) loadNotifyCampaigns();
        import('./history.js').then(m => m.loadHistory());
    } catch (e) {
        toast(e.message, 'error');
    }
}

export async function loadNotifyCampaigns() {
    let checkedDevices = Array.from(document.querySelectorAll('.notify-target-device:checked')).map(c => c.value);
    const tbody = $('notifyCampaignsBody');
    if (!tbody) return;

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
                    const devObj   = _deviceCache.find(d => d.id == devId);
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
        console.error('loadNotifyCampaigns failed', e);
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:15px; font-size:12px; color:var(--danger);">Error loading campaigns.</div></td></tr>`;
    }
}

export async function cancelNotifyCampaign(id) {
    if (!confirm('Cancel this recurring notification campaign?')) return;
    try {
        await api('DELETE', `/api/v1/notifications/${id}`);
        toast('Campaign cancelled', 'success');
        loadNotifyCampaigns();
    } catch (e) {
        toast(e.message, 'error');
    }
}
