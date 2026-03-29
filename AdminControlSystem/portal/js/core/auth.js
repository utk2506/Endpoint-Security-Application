/**
 * core/auth.js
 * Authentication check, role loading, viewer restrictions, logout helpers.
 */

import { api } from './api.js';
import { toast } from './utils.js';

export function checkAuth() {
    const token = localStorage.getItem('token');
    if (!token && window.location.pathname !== '/portal/login.html') {
        window.location.href = '/portal/login.html';
    }
    return token;
}

export function showLogoutModal() {
    const m = document.getElementById('logoutModal');
    if (m) m.classList.add('show');
}

export function hideLogoutModal() {
    const m = document.getElementById('logoutModal');
    if (m) m.classList.remove('show');
}

export function performLogout() {
    localStorage.removeItem('token');
    window.location.href = '/portal/login.html';
}

// Shared mutable role state — read by feature modules via getRole()
let _userRole = 'admin';
export function getRole() { return _userRole; }

export async function loadUserRole() {
    try {
        const me = await api('GET', '/api/auth/me');
        if (me && me.role) {
            _userRole = me.role;
            if (_userRole === 'viewer') {
                applyViewerRestrictions();
            }
            const badge = document.getElementById('roleBadge');
            if (badge) {
                badge.textContent = _userRole === 'admin' ? '🛡️ Admin' : '👁️ Viewer';
                badge.title       = _userRole === 'admin' ? 'Full access' : 'Read-only access';
            }
        }
    } catch (e) { /* silently ignore, default is admin */ }
}

export function applyViewerRestrictions() {
    const adminOnlyIds = [
        'btnGrant', 'btnRevoke', 'btnCheck', 'sendShellBtn', 'openTerminalBtn',
        'btnCreateUser', 'sendNotificationBtn', 'btnGenerateOtp', 'btnUploadVersion'
    ];
    adminOnlyIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.disabled = true;
            el.title    = 'Admin role required';
            el.style.opacity = '0.4';
            el.style.cursor  = 'not-allowed';
        }
    });
}
