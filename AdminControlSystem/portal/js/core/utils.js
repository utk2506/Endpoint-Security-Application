/**
 * core/utils.js — Shared utility functions
 * Imported by every feature module that needs DOM helpers, formatting, or toasts.
 */

// ── DOM shorthand ──────────────────────────────────────────────────────────
export function $(id) { return document.getElementById(id); }

// ── Date Formatting ────────────────────────────────────────────────────────
export function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    const day   = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year  = d.getFullYear();
    let hoursNum = d.getHours();
    const ampm   = hoursNum >= 12 ? 'PM' : 'AM';
    hoursNum     = hoursNum % 12 || 12;
    const hoursStr = String(hoursNum).padStart(2, '0');
    const mins   = String(d.getMinutes()).padStart(2, '0');
    const secs   = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month}/${year} ${hoursStr}:${mins}:${secs} ${ampm}`;
}

// ── Semantic Version Compare ───────────────────────────────────────────────
export function semverCompare(a, b) {
    const pa = (a || '').split('.').map(n => parseInt(n, 10) || 0);
    const pb = (b || '').split('.').map(n => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
        if ((pa[i] || 0) > (pb[i] || 0)) return  1;
        if ((pa[i] || 0) < (pb[i] || 0)) return -1;
    }
    return 0;
}

// ── XSS-Safe HTML Encoding ─────────────────────────────────────────────────
export function escapeHtml(str) {
    if (str == null) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

export function escapeAttr(str) {
    if (str == null) return '';
    return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// ── Toast Notifications ────────────────────────────────────────────────────
export function toast(message, type = 'info') {
    const container = $('toastContainer');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
    el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
    container.appendChild(el);
    setTimeout(() => {
        el.classList.add('toast-exit');
        setTimeout(() => el.remove(), 300);
    }, 3500);
}

// ── Server Connection Indicator ────────────────────────────────────────────
export function setConnected(online) {
    const dot  = $('connectionDot');
    const text = $('connectionText');
    if (!dot || !text) return;
    if (online) {
        dot.classList.remove('offline');
        text.textContent = 'Connected to server';
    } else {
        dot.classList.add('offline');
        text.textContent = 'Server unreachable';
    }
}

// ── Operations Result Box ──────────────────────────────────────────────────
export function showResult(type, icon, text) {
    const box = $('resultBox');
    if (!box) return;
    box.className = `result-box show ${type}`;
    $('resultIcon').textContent = icon;
    $('resultText').textContent = text;
}

export function hideResult() {
    const box = $('resultBox');
    if (box) box.className = 'result-box';
}

// ── Idle / Duration Formatting ─────────────────────────────────────────────
export function formatIdle(sec) {
    if (sec == null) return '—';
    const s = Math.max(0, parseInt(sec, 10));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    if (m < 60) return `${m}m ${r}s`;
    const h  = Math.floor(m / 60);
    const mm = m % 60;
    return `${h}h ${mm}m`;
}
