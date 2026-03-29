/**
 * features/devices.js
 * Device list loading, dropdown population, command button state.
 */

import { api } from '../core/api.js';
import { $, escapeHtml, escapeAttr, setConnected } from '../core/utils.js';
import { refreshAdminList } from './adminList.js';
import { renderSysInfo }    from './sysInfo.js';
import { renderPatchStatus } from './maintenance.js';

// Shared mutable state — read by other modules via getters
export let _deviceCache   = [];
export let selectedDeviceId = null;
export let currentAdminList = [];

export function setSelectedDeviceId(id) { selectedDeviceId = id; }
export function setCurrentAdminList(list) { currentAdminList = list; }

export async function loadDevices() {
    try {
        const devices = await api('GET', '/devices');
        _deviceCache      = devices;
        window._allDevices = devices;
        setConnected(true);

        if (typeof window.onDashboardDataLoaded === 'function') window.onDashboardDataLoaded();

        const select        = $('deviceSelect');
        const filterSelect  = $('filterDevice');
        const evtFilterSelect = $('evtFilterDevice');
        const blDeviceSelect = $('bitlockerDevice');
        const activitySelect = $('activityDevice');
        const otpSelect     = $('otpDeviceSelect');
        const patchSelect   = $('patchDeviceSelect');

        const currentVal       = select ? select.value : '';
        const currentFilterVal = filterSelect  ? filterSelect.value  : '';
        const currentEvtFilterVal = evtFilterSelect ? evtFilterSelect.value : '';
        const currentBlVal     = blDeviceSelect ? blDeviceSelect.value : '';
        const currentActVal    = activitySelect ? activitySelect.value : '';
        const currentOtpVal    = otpSelect  ? otpSelect.value  : '';
        const currentPatchVal  = patchSelect ? patchSelect.value : '';

        if (select) select.innerHTML = '<option value="">— Select a device —</option>';
        if (filterSelect) filterSelect.innerHTML = '<option value="">All Devices</option>';
        if (evtFilterSelect) evtFilterSelect.innerHTML = '<option value="">All Devices</option>';
        if (blDeviceSelect) blDeviceSelect.innerHTML = '<option value="">— Select a device —</option>';
        if (activitySelect) activitySelect.innerHTML = '<option value="">All devices</option>';
        if (otpSelect) otpSelect.innerHTML = '<option value="">— Select a device —</option>';
        if (patchSelect) patchSelect.innerHTML = '<option value="">All devices</option>';

        const now = new Date();
        devices.forEach(d => {
            const lastSeen   = new Date(d.last_seen);
            const diff       = now - lastSeen;
            const isOnline   = !d.is_uninstalled && diff < 30000 && diff > -60000;
            const isUninstalled = d.is_uninstalled;
            const statusIcon = isUninstalled ? '⬜' : (isOnline ? '🟢' : '🔴');

            if (select) {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = `${statusIcon} ${d.hostname}  (${d.ip_address})`;
                select.appendChild(opt);
            }

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

        // Restore selections
        if (select && currentVal && Array.from(select.options).some(o => o.value === currentVal)) select.value = currentVal;
        if (filterSelect && currentFilterVal)   filterSelect.value   = currentFilterVal;
        if (evtFilterSelect && currentEvtFilterVal) evtFilterSelect.value = currentEvtFilterVal;
        if (blDeviceSelect && currentBlVal)     blDeviceSelect.value = currentBlVal;
        if (activitySelect && currentActVal)    activitySelect.value = currentActVal;
        if (otpSelect && currentOtpVal)         otpSelect.value      = currentOtpVal;
        if (patchSelect && currentPatchVal)     patchSelect.value    = currentPatchVal;

        // Rebuild notify device list
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

        if ($('statDevices')) $('statDevices').textContent = devices.length;

        // Auto-refresh sysinfo modal if open
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

export function updateNotifyCount() {
    const checked = document.querySelectorAll('.notify-target-device:checked').length;
    const counter = $('notifyTargetCount');
    if (counter) counter.textContent = checked;
}

export function populateUserDropdown() {
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

export function updateCommandButtons() {
    const select   = $('userSelect');
    const btnGrant = $('btnGrant');
    const btnRevoke= $('btnRevoke');

    if (!select || !btnGrant || !btnRevoke) return;

    const username = select.value;

    if (!username) {
        btnGrant.disabled  = false;
        btnRevoke.disabled = false;
        btnGrant.style.opacity  = '1';
        btnRevoke.style.opacity = '1';
        return;
    }

    const isAdmin = currentAdminList.includes(username);
    if (isAdmin) {
        btnGrant.disabled  = true;
        btnGrant.style.opacity  = '0.4';
        btnRevoke.disabled = false;
        btnRevoke.style.opacity = '1';
    } else {
        btnGrant.disabled  = false;
        btnGrant.style.opacity  = '1';
        btnRevoke.disabled = true;
        btnRevoke.style.opacity = '0.4';
    }
}

// Wire up the global device selector
document.addEventListener('DOMContentLoaded', () => {
    const sel = $('deviceSelect');
    if (sel) {
        sel.addEventListener('change', function () {
            selectedDeviceId = this.value || null;
            // hideResult is imported lazily to avoid circular dep via window
            if (typeof window.hideResult === 'function') window.hideResult();
            if (selectedDeviceId) {
                populateUserDropdown();
                refreshAdminList();
            }
        });
    }
});
