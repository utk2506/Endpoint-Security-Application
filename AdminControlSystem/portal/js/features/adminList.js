/**
 * features/adminList.js
 * Refresh admin user list on device, quick-revoke shortcut.
 */

import { api } from '../core/api.js';
import { $, escapeHtml, escapeAttr, toast } from '../core/utils.js';
import { selectedDeviceId, setCurrentAdminList, updateCommandButtons } from './devices.js';

export async function refreshAdminList() {
    if (!selectedDeviceId) return;

    try {
        const data  = await api('GET', `/admin_list/${selectedDeviceId}`);
        const tbody = $('adminTableBody');

        if (!data.admin_users || data.admin_users.length === 0) {
            setCurrentAdminList([]);
            if (tbody) tbody.innerHTML = `<tr><td colspan="3">
                <div class="empty-state">
                    <span class="icon">📋</span>
                    No admin data yet — click Check Status
                </div>
            </td></tr>`;
            if ($('statAdmins')) $('statAdmins').textContent = '0';
            updateCommandButtons();
            return;
        }

        setCurrentAdminList(data.admin_users);
        if ($('statAdmins')) $('statAdmins').textContent = data.admin_users.length;
        updateCommandButtons();

        if (tbody) {
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
            `;
            }).join('');
        }
    } catch (e) {
        console.error('Failed to load admin list:', e);
    }
}

export function quickRevoke(username) {
    const select = $('userSelect');
    if (select) {
        select.innerHTML = `<option value="${escapeAttr(username)}">${escapeHtml(username)}</option>` + select.innerHTML;
        select.value = username;
        updateCommandButtons();
    }
    // Dynamically import to avoid circular at load time
    import('./operations.js').then(m => m.revokeAdmin());
}
