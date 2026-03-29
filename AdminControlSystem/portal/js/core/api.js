/**
 * core/api.js — Central API fetch wrapper
 * All features import { api, API_BASE, WS_BASE } from this module.
 */

export const API_BASE = window.location.origin;
export const WS_BASE  = window.location.origin.replace(/^http/, 'ws');

/**
 * Authenticated JSON fetch helper.
 * Automatically attaches the Bearer token and redirects on 401.
 *
 * @param {'GET'|'POST'|'DELETE'|'PUT'|'PATCH'} method
 * @param {string} path  — server-relative path e.g. '/devices'
 * @param {object|null} body — JSON-serialisable body (omit for GET)
 * @returns {Promise<any>}
 */
export async function api(method, path, body = null) {
    const token = localStorage.getItem('token');
    const opts = {
        method,
        headers: {
            'Content-Type':  'application/json',
            'Authorization': `Bearer ${token}`,
        },
    };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${API_BASE}${path}`, opts);

    if (res.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/portal/login.html';
        return;
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }

    return res.json();
}
