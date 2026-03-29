/**
 * features/operations.js
 * Grant, Revoke, Check Status, Create User actions.
 */

import { api } from '../core/api.js';
import { $, toast, showResult } from '../core/utils.js';
import { selectedDeviceId } from './devices.js';
import { loadHistory } from './history.js';
import { refreshAdminList } from './adminList.js';

export async function checkStatus() {
    if (!selectedDeviceId) { toast('Please select a device first', 'error'); return; }
    try {
        showResult('info', '🔄', 'Sending check command to agent…');
        await api('POST', '/send_command', { device_id: selectedDeviceId, action: 'check' });
        toast('Check command sent — waiting for agent response', 'info');
        loadHistory();
        setTimeout(refreshAdminList, 6000);
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

export async function grantAdmin() {
    const username = $('userSelect')?.value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Select a user', 'error'); return; }

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
        if (expiresAtInput) expiresAtInput.value = '';
        loadHistory();
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

export async function revokeAdmin() {
    const username = $('userSelect')?.value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!username) { toast('Select a user', 'error'); return; }

    try {
        showResult('info', '🔄', `Revoking admin from "${username}"…`);
        await api('POST', '/send_command', { device_id: selectedDeviceId, action: 'revoke', username });
        toast(`Revoke command queued for "${username}"`, 'success');
        showResult('success', '✅', `Revoke command queued for "${username}"`);
        loadHistory();
    } catch (e) {
        showResult('error', '❌', e.message);
        toast(e.message, 'error');
    }
}

export function openCreateUserModal() {
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    $('newUserName').value = '';
    $('newUserPass').value = '';
    $('createUserModal').classList.add('show');
}

export function closeCreateUserModal() {
    $('createUserModal').classList.remove('show');
}

export async function submitCreateUser() {
    const username = $('newUserName').value.trim();
    const password = $('newUserPass').value;
    if (!username || !password) { toast('Username and password are required', 'error'); return; }

    try {
        toast(`Creating user "${username}"…`, 'info');
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'create_user',
            username,
            payload: password,
        });
        toast(`Create command queued for "${username}"`, 'success');
        closeCreateUserModal();
        loadHistory();
    } catch (e) {
        toast(`Failed to create user: ${e.message}`, 'error');
    }
}
