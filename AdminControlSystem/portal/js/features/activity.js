/**
 * features/activity.js
 * Activity stream, charts (status ring, app usage bar), device/user summary,
 * hourly heatmap, and CSV export.
 */

import { api } from '../core/api.js';
import { $, formatDate, escapeHtml, toast } from '../core/utils.js';
import { _deviceCache } from './devices.js';

let activityPage       = 1;
let activityLimit      = 20;
let activityTotalPages = 1;
let _lastActivityItems = [];

let statusRingInstance  = null;
let appUsageBarInstance = null;
let sessionTable        = null;

function activityFilters() {
    const toIso = (v) => { if (!v) return null; const d = new Date(v); return isNaN(d.getTime()) ? null : d.toISOString(); };
    return {
        device: $('activityDevice')?.value || '',
        username: $('activityUser')?.value || '',
        department: $('activityDepartment')?.value || '',
        application: $('activityApplication')?.value || '',
        activity_state: $('activityState')?.value || '',
        date_from: toIso($('activityFrom')?.value),
        date_to: toIso($('activityTo')?.value),
        min_duration: $('activityMinDuration')?.value || '',
        search: $('activitySearch')?.value || '',
    };
}

export function applyActivityFilters() {
    loadActivity(1);
    loadActivityUsers();
    loadDeviceSummary();
    loadHourlyHeatmap();
    loadUserSummary();
    loadActivityKpis();
    loadAnalyticsCharts();
    loadSessionTable(true);
}

export function resetActivityFilters() {
    ['activityDevice','activityUser','activityDepartment','activityApplication','activityState','activityFrom','activityTo','activityMinDuration','activitySearch']
        .forEach(id => { const el = $(id); if (el) el.value = ''; });
    applyActivityFilters();
}

export async function loadActivityFilters() {
    try {
        const data = await api('GET', '/api/v1/activity/filters');
        const setOptions = (id, values, placeholder) => {
            const el = $(id);
            if (!el) return;
            el.innerHTML = `<option value="">${placeholder}</option>`;
            values.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                el.appendChild(opt);
            });
        };
        setOptions('activityUser', data.users || [], 'All users');
        setOptions('activityDevice', data.devices || [], 'All devices');
        setOptions('activityDepartment', data.departments || [], 'All departments');
        setOptions('activityApplication', data.applications || [], 'All apps');
    } catch (e) {
        console.warn('loadActivityFilters failed', e);
    }
}

function formatHourLabel(h) {
    if (h == null || isNaN(h)) return '—';
    const hrs = Math.floor(h);
    const mins = Math.round((h - hrs) * 60);
    return `${String(hrs).padStart(2,'0')}:${String(mins).padStart(2,'0')}`;
}

function formatIdle(sec) {
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

export function renderStatusRing(active, idle) {
    const ctx = document.getElementById('statusRingChart');
    if (!ctx) return;
    if (statusRingInstance) statusRingInstance.destroy();

    const total      = active + idle;
    const activePerc = total > 0 ? ((active / total) * 100).toFixed(0) : 0;
    const pctEl      = document.getElementById('activePercentageText');
    if (pctEl) pctEl.textContent = activePerc + '%';

    statusRingInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Active', 'Idle'],
            datasets: [{ data: [active, idle], backgroundColor: ['#4633ff', 'rgba(0,0,0,0.05)'], borderWidth: 0, hoverOffset: 4 }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '80%',
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `${c.label}: ${formatIdle(c.raw)}` } }
            }
        }
    });
}

export function renderAppUsageBarChart(labelMap) {
    const ctx = document.getElementById('appUsageBarChart');
    if (!ctx) return;
    if (appUsageBarInstance) appUsageBarInstance.destroy();

    const sorted = Object.entries(labelMap)
        .filter(([k]) => k.toLowerCase() !== 'idle')
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);

    appUsageBarInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sorted.map(x => x[0]),
            datasets: [{
                label: 'Usage Time',
                data:  sorted.map(x => x[1]),
                backgroundColor: 'rgba(70, 51, 255, 0.8)',
                borderRadius: 5, borderWidth: 0, barThickness: 15
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `Focus Time: ${formatIdle(c.raw)}` } }
            },
            scales: {
                x: { display: false, grid: { display: false } },
                y: { grid: { display: false }, ticks: { color: 'var(--text-3)', font: { size: 11 } } }
            }
        }
    });
}

export async function loadActivity(page = 1) {
    try {
        activityPage = page;
        let url = `/api/v1/activity?page=${activityPage}&limit=${activityLimit}`;
        const filters = activityFilters();
        if (filters.device) url += `&device_id=${encodeURIComponent(filters.device)}`;
        if (filters.username) url += `&username=${encodeURIComponent(filters.username)}`;
        if (filters.department) url += `&department=${encodeURIComponent(filters.department)}`;
        if (filters.application) url += `&process_name=${encodeURIComponent(filters.application)}`;
        if (filters.activity_state) url += `&activity_state=${encodeURIComponent(filters.activity_state)}`;
        if (filters.search) url += `&search=${encodeURIComponent(filters.search)}`;
        const df = filters.date_from;
        const dt = filters.date_to;
        if (df) url += `&date_from=${encodeURIComponent(df)}`;
        if (dt) url += `&date_to=${encodeURIComponent(dt)}`;

        const data  = await api('GET', url);
        const items = data.items || [];
        _lastActivityItems = items;
        const total = data.total || 0;

        // Stats & Charts
        let statsUrl = `/api/v1/activity/stats?`;
        if (filters.device) statsUrl += `device_id=${encodeURIComponent(filters.device)}&`;
        if (filters.username) statsUrl += `username=${encodeURIComponent(filters.username)}&`;
        if (filters.department) statsUrl += `department=${encodeURIComponent(filters.department)}&`;
        if (filters.application) statsUrl += `process_name=${encodeURIComponent(filters.application)}&`;
        if (filters.activity_state) statsUrl += `activity_state=${encodeURIComponent(filters.activity_state)}&`;
        let statsDf = df;
        if (!statsDf) {
            const yesterday = new Date();
            yesterday.setHours(yesterday.getHours() - 24);
            statsDf = yesterday.toISOString();
        }
        statsUrl += `date_from=${encodeURIComponent(statsDf)}&`;
        if (dt) statsUrl += `date_to=${encodeURIComponent(dt)}&`;

        try {
            const stats      = await api('GET', statsUrl);
            const idleSec    = stats.total_idle_seconds || 0;
            const deviceCount= stats.device_count || 1;
            const labelMap   = stats.process_distribution || {};

            let activeSec = 0;
            for (const [proc, sec] of Object.entries(labelMap)) {
                if (proc.toLowerCase() !== 'idle') activeSec += sec;
            }

            if ($('statIdleTime'))   $('statIdleTime').textContent   = formatIdle(idleSec);
            if ($('statActiveTime')) $('statActiveTime').textContent  = formatIdle(activeSec);

            const dcEl = $('activityDeviceCount');
            if (dcEl) {
                if (deviceCount > 1) {
                    dcEl.textContent     = `${deviceCount} Devices`;
                    dcEl.style.display   = 'inline-block';
                } else {
                    dcEl.style.display   = 'none';
                }
            }

            renderStatusRing(activeSec, idleSec);
            renderAppUsageBarChart(labelMap);

            const detailsBody = document.getElementById('activityDetailsBody');
            if (detailsBody) {
                const groupedApps = Object.entries(labelMap)
                    .filter(([p]) => p.toLowerCase() !== 'idle')
                    .sort((a, b) => b[1] - a[1]);

                if (groupedApps.length === 0) {
                    detailsBody.innerHTML = '<tr><td colspan="3"><div class="empty-state">No app activity recorded.</div></td></tr>';
                } else {
                    const windowMap = {};
                    items.forEach(it => {
                        const p = it.process_name || 'Unknown';
                        if (!windowMap[p]) windowMap[p] = new Set();
                        if (it.window_title) windowMap[p].add(it.window_title);
                    });
                    detailsBody.innerHTML = groupedApps.map(([proc, sec]) => {
                        const titles     = Array.from(windowMap[proc] || []).slice(0, 3).join(', ');
                        const titlesDisp = titles ? `<small style="color:var(--text-3)">${escapeHtml(titles)}</small>` : '—';
                        return `<tr>
                            <td><strong>${escapeHtml(proc)}</strong></td>
                            <td>${titlesDisp}</td>
                            <td><span class="badge badge-info">${formatIdle(sec)}</span></td>
                        </tr>`;
                    }).join('');
                }
            }
        } catch (e) {
            console.error('Stats fetching failed', e);
        }

        const limit    = data.limit || activityLimit;
        const pageResp = data.page  || activityPage;
        activityTotalPages = Math.max(1, Math.ceil(total / limit));
        activityPage       = pageResp;

        if ($('activityTotal'))      $('activityTotal').textContent      = `${total} events`;
        if ($('activityPageNumber')) $('activityPageNumber').textContent = String(activityPage);

        const tbody = $('activityTableBody');
        if (!tbody) return;

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><span class="ei">📭</span>No activity yet</div></td></tr>`;
        } else {
            tbody.innerHTML = items.map(i => {
                const idle       = formatIdle(i.idle_seconds);
                const inputTxt   = `${i.click_count || 0}c / ${i.keypress_count || 0}k`;
                const deviceObj  = (_deviceCache || []).find(x => x.id === i.device_id);
                const deviceLabel= deviceObj ? deviceObj.hostname : (i.device_id || '');
                const userLabel  = i.username ? escapeHtml(i.username) : '<span style="color:var(--text-3)">—</span>';
                return `<tr>
                    <td>${formatDate(i.timestamp)}</td>
                    <td>${escapeHtml(deviceLabel)}</td>
                    <td>${userLabel}</td>
                    <td>${escapeHtml(i.window_title  || '—')}</td>
                    <td>${escapeHtml(i.process_name  || '—')}</td>
                    <td>${idle}</td>
                    <td>${inputTxt}</td>
                </tr>`;
            }).join('');
        }

        if ($('activityPageInfo')) {
            const startIdx = total === 0 ? 0 : ((activityPage - 1) * limit) + 1;
            const endIdx   = Math.min(activityPage * limit, total);
            $('activityPageInfo').textContent = `${startIdx}-${endIdx} of ${total} results`;
        }

        if ($('btnActivityPrev')) $('btnActivityPrev').disabled = activityPage <= 1;
        if ($('btnActivityNext')) $('btnActivityNext').disabled = activityPage >= activityTotalPages;

        // Live auto-refresh
        if (!window._activityRefreshInterval) {
            window._activityRefreshInterval = setInterval(() => {
                const view = document.getElementById('view-activity');
                if (view && view.style.display !== 'none') {
                    loadActivity(activityPage);
                }
            }, 30000);
        }
    } catch (err) {
        const tbody = $('activityTableBody');
        if (tbody) tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><span class="ei">⚠️</span>${err.message || 'Failed to load activity'}</div></td></tr>`;
    }
}

export function activityPrevPage() { if (activityPage > 1) loadActivity(activityPage - 1); }
export function activityNextPage() { if (activityPage < activityTotalPages) loadActivity(activityPage + 1); }

export async function loadActivityUsers() {
    try {
        const device = $('activityDevice')?.value;
        let url = '/api/v1/activity/users';
        if (device) url += `?device_id=${encodeURIComponent(device)}`;
        const data = await api('GET', url);
        const sel  = $('activityUser');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">All users</option>';
        (data.users || []).forEach(u => {
            const opt   = document.createElement('option');
            opt.value   = u;
            opt.textContent = u;
            sel.appendChild(opt);
        });
        if (current) sel.value = current;
    } catch (e) {
        console.warn('loadActivityUsers failed', e);
    }
}

export async function loadDeviceSummary() {
    const tbody   = $('deviceSummaryBody');
    const countEl = $('deviceSummaryCount');
    if (!tbody) return;
    try {
        const data    = await api('GET', '/api/v1/activity/device-summary');
        const devices = data.devices || [];
        if (countEl) countEl.textContent = `${devices.length} device${devices.length !== 1 ? 's' : ''}`;
        if (devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state">No device activity data</div></td></tr>';
            return;
        }
        tbody.innerHTML = devices.map(d => {
            const riskColor = d.risk_score >= 70 ? 'var(--danger)' : d.risk_score >= 40 ? 'var(--warning)' : 'var(--success)';
            const users     = d.users && d.users.length ? d.users.join(', ') : '—';
            return `<tr>
                <td><strong>${escapeHtml(d.hostname || d.device_id)}</strong></td>
                <td><span class="badge badge-completed">${formatIdle(d.active_seconds)}</span></td>
                <td><span style="color:var(--warning)">${formatIdle(d.idle_seconds)}</span></td>
                <td title="${escapeHtml(users)}">${d.user_count} user${d.user_count !== 1 ? 's' : ''} <small style="color:var(--text-3);">(${escapeHtml(users.length > 40 ? users.slice(0,40)+'…' : users)})</small></td>
                <td>${escapeHtml(d.top_app || '—')}</td>
                <td>${d.total_clicks || 0} / ${d.total_keypresses || 0}</td>
                <td><span style="font-weight:700; color:${riskColor}">${d.risk_score}</span>/100</td>
            </tr>`;
        }).join('');
    } catch (e) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state">Error loading device summary</div></td></tr>';
    }
}

export async function loadHourlyHeatmap() {
    const container = $('hourlyHeatmap');
    const label     = $('heatmapDeviceLabel');
    if (!container) return;
    try {
        const device   = $('activityDevice')?.value;
        let url = '/api/v1/activity/hourly';
        if (device) url += `?device_id=${encodeURIComponent(device)}`;
        const username = $('activityUser')?.value;
        if (username) url += (device ? '&' : '?') + `username=${encodeURIComponent(username)}`;
        if (label) label.textContent = device ? '(device filtered)' : '(all devices)';

        const data    = await api('GET', url);
        const buckets = data.hourly || [];
        const maxActive = Math.max(...buckets.map(b => b.active_seconds), 1);

        container.innerHTML = buckets.map(b => {
            const ratio     = b.active_seconds / maxActive;
            const idleRatio = b.events > 0 ? (b.idle_seconds / (b.active_seconds + b.idle_seconds)) : 1;
            let bg = '#ecf0f1';
            if (b.events > 0) {
                bg = idleRatio > 0.7 ? '#f39c12' : ratio > 0.6 ? '#27ae60' : ratio > 0.3 ? '#2ecc71' : '#f0faf3';
            }
            const tip = `Hour ${b.hour}:00 — Active: ${formatIdle(b.active_seconds)}, Idle: ${formatIdle(b.idle_seconds)}, Events: ${b.events}`;
            return `<div title="${escapeHtml(tip)}" style="
                background:${bg}; border-radius:4px; height:48px;
                display:flex; flex-direction:column; align-items:center; justify-content:center;
                font-size:10px; color:${b.events > 0 ? '#fff' : 'var(--text-3)'};
                cursor:default; transition:transform 0.15s;
            " onmouseover="this.style.transform='scale(1.1)'" onmouseout="this.style.transform=''">
                <span>${b.hour}h</span>
            </div>`;
        }).join('');
    } catch (e) {
        if (container) container.innerHTML = '<div style="color:var(--text-3); padding:10px;">Error loading heatmap</div>';
    }
}

export async function loadUserSummary() {
    const tbody   = $('userSummaryBody');
    const countEl = $('userSummaryCount');
    if (!tbody) return;
    try {
        const device = $('activityDevice')?.value;
        let url = '/api/v1/activity/summary';
        if (device) url += `?device_id=${encodeURIComponent(device)}`;
        const data  = await api('GET', url);
        const users = data.users || [];
        if (countEl) countEl.textContent = `${users.length} user${users.length !== 1 ? 's' : ''}`;
        if (users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">No user activity data</div></td></tr>';
            return;
        }
        tbody.innerHTML = users.map(u => {
            const topApps = (u.top_apps || []).slice(0, 3).map(a => escapeHtml(a.process)).join(', ') || '—';
            return `<tr>
                <td><strong>👤 ${escapeHtml(u.username)}</strong></td>
                <td><span class="badge badge-completed">${formatIdle(u.active_seconds)}</span></td>
                <td><span style="color:var(--warning)">${formatIdle(u.idle_seconds)}</span></td>
                <td>${u.total_clicks     || 0}</td>
                <td>${u.total_keypresses || 0}</td>
                <td><small style="color:var(--text-3)">${topApps}</small></td>
            </tr>`;
        }).join('');
    } catch (e) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">Error loading user summary</div></td></tr>';
    }
}

// ── KPIs & Analytics (ECharts) ──────────────────────────────────────────────
export async function loadActivityKpis() {
    try {
        const f = activityFilters();
        let url = '/api/v1/activity/kpis?';
        if (f.device) url += `device_id=${encodeURIComponent(f.device)}&`;
        if (f.username) url += `username=${encodeURIComponent(f.username)}&`;
        if (f.date_from) url += `date_from=${encodeURIComponent(f.date_from)}&`;
        if (f.date_to) url += `date_to=${encodeURIComponent(f.date_to)}&`;
        const data = await api('GET', url);
        const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
        set('kpiActiveUsers', data.active_users ?? '—');
        set('kpiLoggedToday', data.logged_in_today ?? '—');
        set('kpiAvgLogin', formatHourLabel(data.avg_login_hour));
        set('kpiAvgLogout', formatHourLabel(data.avg_logout_hour));
        set('kpiAvgWork', data.avg_work_duration_hours ? `${data.avg_work_duration_hours}h` : '—');
        set('kpiIdlePct', data.idle_percentage != null ? `${data.idle_percentage}%` : '—');
        set('kpiProd', data.productivity_score != null ? `${data.productivity_score}%` : '—');
    } catch (e) {
        console.warn('loadActivityKpis error', e);
    }
}

export async function loadAnalyticsCharts() {
    try {
        const f = activityFilters();
        let url = '/api/v1/activity/analytics?';
        if (f.device) url += `device_id=${encodeURIComponent(f.device)}&`;
        if (f.username) url += `username=${encodeURIComponent(f.username)}&`;
        if (f.department) url += `department=${encodeURIComponent(f.department)}&`;
        if (f.application) url += `process_name=${encodeURIComponent(f.application)}&`;
        if (f.activity_state) url += `activity_state=${encodeURIComponent(f.activity_state)}&`;
        if (f.date_from) url += `date_from=${encodeURIComponent(f.date_from)}&`;
        if (f.date_to) url += `date_to=${encodeURIComponent(f.date_to)}&`;
        const data = await api('GET', url);

        renderLoginHistogram(data.login_histogram || [], data.logout_histogram || []);
        renderTimelineChart(data.activity_series || {});
        renderAppDonut(data.top_apps || [], data.other_apps_seconds || 0);
        renderUserProductivity(data.per_user || []);
        renderLockStatus(data.state_snapshot || {});
    } catch (e) {
        console.warn('loadAnalyticsCharts error', e);
    }
}

function renderLoginHistogram(login_hist, logout_hist) {
    const el = document.getElementById('chartLoginHistogram');
    if (!el || !window.echarts) return;
    const chart = echarts.init(el);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['Login', 'Logout'], textStyle: { color: '#ccc' } },
        grid: { left: 40, right: 10, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: Array.from({length:24}, (_,i)=>`${i}:00`), axisLabel:{color:'#ccc'} },
        yAxis: { type: 'value', axisLabel:{color:'#ccc'} },
        series: [
            { name:'Login', type:'bar', data: login_hist, itemStyle:{color:'#1E90FF'} },
            { name:'Logout', type:'bar', data: logout_hist, itemStyle:{color:'#00E676'} }
        ]
    });
}

function renderTimelineChart(series) {
    const el = document.getElementById('chartTimeline');
    if (!el || !window.echarts) return;
    const chart = echarts.init(el);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data:['Active','Idle','Locked'], textStyle:{color:'#ccc'} },
        grid: { left: 40, right: 10, top: 30, bottom: 30 },
        xAxis: { type:'category', data: series.labels || [], axisLabel:{color:'#ccc'} },
        yAxis: { type:'value', axisLabel:{color:'#ccc'} },
        dataZoom: [{ type:'inside' }, { type:'slider' }],
        series: [
            { name:'Active', type:'line', areaStyle:{opacity:0.3}, data: series.active || [], color:'#27ae60' },
            { name:'Idle', type:'line', areaStyle:{opacity:0.2}, data: series.idle || [], color:'#f39c12' },
            { name:'Locked', type:'line', areaStyle:{opacity:0.2}, data: series.locked || [], color:'#e67e22' },
        ]
    });
}

function renderAppDonut(topApps, otherSeconds) {
    const el = document.getElementById('chartAppDonut');
    if (!el || !window.echarts) return;
    const chart = echarts.init(el);
    const data = (topApps || []).map(a => ({ name:a.name, value:a.seconds }));
    if (otherSeconds) data.push({ name:'Other', value: otherSeconds });
    chart.setOption({
        tooltip: { trigger:'item' },
        series: [{
            type:'pie',
            radius:['45%','70%'],
            data,
            label: { color:'#ddd' }
        }]
    });
}

function renderUserProductivity(perUser) {
    const el = document.getElementById('chartUserProductivity');
    if (!el || !window.echarts) return;
    const chart = echarts.init(el);
    const top = (perUser || []).slice(0,8);
    chart.setOption({
        tooltip:{ trigger:'axis' },
        legend:{ data:['Active','Idle','Locked'], textStyle:{color:'#ccc'} },
        grid:{ left: 80, right: 20, top: 30, bottom: 30 },
        xAxis:{ type:'value', axisLabel:{color:'#ccc'} },
        yAxis:{ type:'category', data: top.map(u=>u.username), axisLabel:{color:'#ccc'} },
        series:[
            { name:'Active', type:'bar', stack:'t', data: top.map(u=>Math.round((u.active_seconds||0)/60)), itemStyle:{color:'#27ae60'} },
            { name:'Idle', type:'bar', stack:'t', data: top.map(u=>Math.round((u.idle_seconds||0)/60)), itemStyle:{color:'#f39c12'} },
            { name:'Locked', type:'bar', stack:'t', data: top.map(u=>Math.round((u.locked_seconds||0)/60)), itemStyle:{color:'#e67e22'} },
        ]
    });
}

function renderLockStatus(snapshot) {
    const list = document.getElementById('lockStatusList');
    if (!list) return;
    const colors = { active:'green', idle:'gold', locked:'orange', offline:'red' };
    list.innerHTML = '';
    Object.entries(snapshot).forEach(([state, count]) => {
        const li = document.createElement('li');
        const dot = document.createElement('span');
        dot.className = 'status-dot';
        dot.style.background = colors[state] || 'gray';
        li.appendChild(dot);
        li.appendChild(document.createTextNode(`${state}: ${count}`));
        list.appendChild(li);
    });
}

// ── Sessions table (DataTables server-side) ──────────────────────────────────
export function loadSessionTable(forceReload = false) {
    const f = activityFilters();
    const baseUrl = '/api/v1/activity/sessions';
    const params = new URLSearchParams();
    if (f.device) params.append('device_id', f.device);
    if (f.username) params.append('username', f.username);
    if (f.department) params.append('department', f.department);
    if (f.application) params.append('process_name', f.application);
    if (f.activity_state) params.append('activity_state', f.activity_state);
    if (f.date_from) params.append('date_from', f.date_from);
    if (f.date_to) params.append('date_to', f.date_to);
    if (f.min_duration) params.append('min_duration', f.min_duration);

    if (!sessionTable) {
        sessionTable = window.jQuery && window.jQuery('#sessionTable').DataTable({
            processing: true,
            serverSide: true,
            searching: true,
            ajax: function (data, callback) {
                const fullParams = new URLSearchParams(params.toString());
                fullParams.append('draw', data.draw);
                fullParams.append('start', data.start);
                fullParams.append('length', data.length);
                if (data.search && data.search.value) fullParams.append('search[value]', data.search.value);
                if (data.order && data.order.length) {
                    fullParams.append('order[0][column]', data.order[0].column);
                    fullParams.append('order[0][dir]', data.order[0].dir);
                }
                api('GET', `${baseUrl}?${fullParams.toString()}`)
                    .then(json => callback(json))
                    .catch(err => {
                        console.warn('session table load failed', err);
                        callback({ draw: data.draw, recordsTotal:0, recordsFiltered:0, data:[] });
                    });
            },
            columns: [
                { data:'user' },
                { data:'device' },
                { data:'login' },
                { data:'logout' },
                { data:'active' },
                { data:'idle' },
                { data:'lock_count' },
                { data:'productivity' },
            ]
        });
    } else if (forceReload) {
        sessionTable.ajax.reload();
    }
}
export function exportActivityCSV() {
    if (!_lastActivityItems || _lastActivityItems.length === 0) {
        toast('No activity data to export. Apply filters first.', 'info');
        return;
    }
    const escCsv = v => {
        if (v == null) return '';
        const s = String(v);
        return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const cols = ['Timestamp', 'Device', 'Username', 'Window Title', 'Process', 'Idle (s)', 'Clicks', 'Keypresses'];
    const rows = _lastActivityItems.map(i =>
        [i.timestamp, i.device_id, i.username, i.window_title, i.process_name, i.idle_seconds, i.click_count, i.keypress_count]
        .map(escCsv).join(',')
    );
    const csv  = [cols.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `activity_export_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast(`Exported ${_lastActivityItems.length} rows to CSV`, 'success');
}

export async function generateActivityReport() {
    try {
        const type = $('reportType')?.value || 'daily_activity';
        const fmt  = $('reportFormat')?.value || 'csv';
        const f = activityFilters();
        const payload = {
            type,
            format: fmt,
            device_id: f.device || null,
            username: f.username || null,
            department: f.department || null,
            process_name: f.application || null,
            activity_state: f.activity_state || null,
            date_from: f.date_from,
            date_to: f.date_to,
            min_duration: f.min_duration ? parseInt(f.min_duration, 10) : null,
        };
        const res = await fetch('/api/v1/activity/reports', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`Report failed (${res.status})`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `activity_report.${fmt}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        const stat = $('reportStatus');
        if (stat) stat.textContent = 'Report downloaded';
    } catch (e) {
        const stat = $('reportStatus');
        if (stat) stat.textContent = 'Report failed';
        toast(e.message || 'Report generation failed', 'error');
    }
}
