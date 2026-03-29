/**
 * features/audit.js
 * CSV/PDF audit export via iframe download.
 */

import { API_BASE } from '../core/api.js';
import { toast } from '../core/utils.js';

export async function downloadAuditExport(format) {
    const t = localStorage.getItem('token');
    if (!t) {
        toast('Your session has expired. Please sign in again.', 'error');
        window.location.href = '/portal/login.html';
        return;
    }

    const btnId        = format === 'csv' ? 'btnExportCsv' : 'btnExportPdf';
    const btn          = document.getElementById(btnId);
    const originalText = btn ? btn.textContent : '';

    try {
        if (btn) { btn.disabled = true; btn.textContent = 'Preparing...'; }

        const url    = `${API_BASE}/api/v1/audit/export/${format}?token=${encodeURIComponent(t)}`;
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
        if (btn) { btn.disabled = false; btn.textContent = originalText; }
    }
}
