/**
 * features/activity.js  — Activity Monitoring Dashboard v2
 *
 * Pulls all dashboard data from a single call to:
 *   GET /api/activity/analytics   → KPIs, charts, heatmap, timeline
 *   GET /api/activity/events      → paginated event feed table
 *   GET /api/activity/machines    → machine filter dropdown
 *   GET /api/activity/users       → user filter dropdown
 *
 * All original export names are preserved for dashboard.js compatibility.
 */

import { api } from '../core/api.js';
import { $ } from '../core/utils.js';

// ── State ──────────────────────────────────────────────────────────────────
let _period          = 'daily';   // 'daily' | 'weekly' | 'monthly' | 'yearly' | 'custom'
let _customFrom      = '';
let _customTo        = '';
let _evtPage         = 1;
let _evtTotalPages   = 1;
let _charts          = {};        // { id: Chart }
let _refreshing      = false;
let _autoRefreshTimer    = null;
let _autoRefreshCountdown = 60;

// ── Date Range Helpers ─────────────────────────────────────────────────────
function _getRange(period) {
    const now    = new Date();
    const endDay = new Date(now);
    endDay.setHours(23, 59, 59, 999);

    if (period === 'daily') {
        const start = new Date(now);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: endDay.toISOString() };
    }
    if (period === 'weekly') {
        const start = new Date(now);
        start.setDate(start.getDate() - 6);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: endDay.toISOString() };
    }
    if (period === 'monthly') {
        const start = new Date(now);
        start.setDate(start.getDate() - 29);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: endDay.toISOString() };
    }
    if (period === 'yearly') {
        const start = new Date(now);
        start.setDate(start.getDate() - 364);
        start.setHours(0, 0, 0, 0);
        return { from: start.toISOString(), to: endDay.toISOString() };
    }
    // custom
    const from = _customFrom ? new Date(_customFrom + 'T00:00:00').toISOString() : null;
    const to   = _customTo   ? new Date(_customTo   + 'T23:59:59').toISOString() : null;
    return { from, to };
}

// ── Active Filters ─────────────────────────────────────────────────────────
function _getFilters() {
    const range = _getRange(_period);
    return {
        machine:      $('actMachine')?.value    || '',
        username:     $('actUser')?.value       || '',
        event_type:   $('actEventType')?.value  || '',
        synced:       $('actSynced')?.value     || '',
        search:       $('actSearch')?.value     || '',
        process_name: $('actProcess')?.value    || '',
        date_from:    range.from                || '',
        date_to:      range.to                  || '',
    };
}

function _toQS(obj) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(obj)) {
        if (v !== null && v !== undefined && v !== '') p.append(k, v);
    }
    return p.toString();
}

// ── Chart Lifecycle ────────────────────────────────────────────────────────
function _destroyChart(id) {
    if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── Primary Dashboard Refresh ──────────────────────────────────────────────
async function _refreshDashboard() {
    if (_refreshing) return;
    _refreshing = true;
    try {
        const f  = _getFilters();
        const qs = _toQS({
            machine:    f.machine,
            username:   f.username,
            event:      f.event_type,
            synced:     f.synced,
            search:     f.search,
            date_from:  f.date_from,
            date_to:    f.date_to,
        });
        const qs2 = _toQS({
            machine:   f.machine,
            username:  f.username,
            date_from: f.date_from,
            date_to:   f.date_to,
        });

        const [analyticsRes, appRes] = await Promise.allSettled([
            api('GET', `/api/activity/analytics?${qs}`),
            api('GET', `/api/activity/app-usage?${qs2}`),
        ]);

        if (analyticsRes.status === 'fulfilled') {
            const data = analyticsRes.value;
            _renderKPIs(data.kpis || {});
            _renderLineChart(data.hourly_series || {});
            _renderDonut(data.kpis || {});
            _renderTopMachinesBar(data.top_machines || []);
            _renderSessionAnalysis(data.session_stats || {});
            _renderHeatmap(data.heatmap || {});
            _renderTimeline(data.timeline || {});
            _updateRangeLabel(data.range || {});
        } else {
            console.warn('Activity analytics error:', analyticsRes.reason);
        }

        if (appRes.status === 'fulfilled') {
            const a = appRes.value;
            _renderLoginDistChart(a.login_distribution || []);
            _renderAppDonut(a.app_breakdown || []);
            _renderProductivityChart(a.productivity_by_user || []);
        }
    } catch (err) {
        console.warn('Activity dashboard refresh error:', err);
    } finally {
        _refreshing = false;
    }
}

// ── KPI Cards ──────────────────────────────────────────────────────────────
function _renderKPIs(kpis) {
    const set = (id, v) => { const el = $(id); if (el) el.textContent = v ?? '—'; };
    set('actKpiActive',  kpis.active  ?? 0);
    set('actKpiIdle',    kpis.idle    ?? 0);
    set('actKpiLocked',  kpis.locked  ?? 0);
    set('actKpiOffline', kpis.offline ?? 0);
    set('actKpiTotal',   kpis.total_events ?? 0);
    set('actKpiHealth',  kpis.sync_health != null ? `${kpis.sync_health}%` : '—');

    // also keep legacy stat IDs working
    const set2 = (id, v) => { const el = $(id); if (el) el.textContent = v ?? '—'; };
    set2('kpiActiveUsers',  kpis.active  ?? '—');
    set2('kpiLoggedToday',  kpis.total_events ?? '—');
    set2('kpiIdlePct',      kpis.sync_health != null ? `${100 - kpis.sync_health}%` : '—');
    set2('kpiProd',         kpis.sync_health != null ? `${kpis.sync_health}%` : '—');
}

function _updateRangeLabel(range) {
    const el = $('actRangeLabel');
    if (!el || !range.from) return;
    const fmt = iso => new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    el.textContent = `${fmt(range.from)} → ${fmt(range.to || new Date().toISOString())}`;
}

// ── Line Chart: Active Users Over Time ─────────────────────────────────────
function _renderLineChart(series) {
    _destroyChart('actLineChart');
    const ctx = document.getElementById('actLineChart');
    if (!ctx || !series.labels?.length) return;

    _charts.actLineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: series.labels,
            datasets: [
                {
                    label: 'Active',
                    data: series.active || [],
                    borderColor: '#00E676',
                    backgroundColor: 'rgba(0,230,118,0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                },
                {
                    label: 'Idle',
                    data: series.idle || [],
                    borderColor: '#FFC107',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    borderDash: [4, 3],
                    fill: false,
                    tension: 0.4,
                    pointRadius: 2,
                },
                {
                    label: 'Locked',
                    data: series.locked || [],
                    borderColor: '#FF6B35',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    fill: false,
                    tension: 0.4,
                    pointRadius: 2,
                },
                {
                    label: 'Offline',
                    data: series.offline || [],
                    borderColor: '#FF3864',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    fill: false,
                    tension: 0.4,
                    pointRadius: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: { color: '#9FB6C8', font: { size: 11 }, boxWidth: 10, usePointStyle: true },
                },
                tooltip: { mode: 'index', intersect: false },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(31,53,66,0.7)' },
                    ticks: { color: '#7A8C9A', font: { size: 10 }, maxTicksLimit: 12, maxRotation: 0 },
                },
                y: {
                    min: 0,
                    grid: { color: 'rgba(31,53,66,0.7)' },
                    ticks: { color: '#7A8C9A', font: { size: 10 }, precision: 0 },
                },
            },
        },
    });
}

// ── Donut: Activity Breakdown ──────────────────────────────────────────────
function _renderDonut(kpis) {
    _destroyChart('actDonutChart');
    const ctx = document.getElementById('actDonutChart');
    if (!ctx) return;

    const vals  = [kpis.active || 0, kpis.idle || 0, kpis.locked || 0, kpis.offline || 0];
    const total = vals.reduce((a, b) => a + b, 0) || 1;

    const pctEl = $('actDonutCenter');
    if (pctEl) pctEl.innerHTML = `<div style="font-size:26px;font-weight:800;color:#E8F3FF;line-height:1">${vals[0]}</div><div style="font-size:10px;color:#7A8C9A;margin-top:2px;">of ${total}</div>`;

    // Legend values
    [['actDonutActive', vals[0]], ['actDonutIdle', vals[1]], ['actDonutLocked', vals[2]], ['actDonutOffline', vals[3]]].forEach(([id, v]) => {
        const el = $(id);
        if (el) {
            el.querySelector('.act-donut-val').textContent = v;
            el.querySelector('.act-donut-pct').textContent = `${Math.round((v / total) * 100)}%`;
        }
    });

    _charts.actDonutChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Active', 'Idle', 'Locked', 'Offline'],
            datasets: [{
                data: vals,
                backgroundColor: ['#00E676', '#FFC107', '#FF6B35', '#FF3864'],
                borderWidth: 0,
                hoverOffset: 6,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '74%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: c => `${c.label}: ${c.raw} (${Math.round((c.raw / total) * 100)}%)`,
                    },
                },
            },
        },
    });
}

// ── Top Machines Horizontal Bar ────────────────────────────────────────────
function _renderTopMachinesBar(machines) {
    const el = $('actTopMachinesBar');
    if (!el) return;
    if (!machines.length) {
        el.innerHTML = '<div class="empty-state">No machine activity data</div>';
        return;
    }
    const maxVal = Math.max(...machines.map(m => m.active_minutes), 1);
    el.innerHTML = machines.slice(0, 7).map(m => {
        const pct = Math.max(2, Math.round((m.active_minutes / maxVal) * 100));
        return `<div class="act-bar-row">
            <div class="act-bar-label" title="${m.machine}">${m.machine}</div>
            <div class="act-bar-track"><div class="act-bar-fill" style="width:${pct}%"></div></div>
            <div class="act-bar-val">${m.active_label || '—'}</div>
        </div>`;
    }).join('');
}

// ── Session Duration Analysis ──────────────────────────────────────────────
function _renderSessionAnalysis(stats) {
    const setTxt = (id, v) => { const el = $(id); if (el) el.textContent = v ?? '—'; };
    setTxt('actSessAvg',     stats.avg_label     || '—');
    setTxt('actSessLongest', stats.longest_label || '—');
    setTxt('actSessTotal',   stats.total_sessions ?? 0);

    const el = $('actSessionBuckets');
    if (!el) return;
    const buckets  = stats.buckets || [];
    const maxCount = Math.max(...buckets.map(b => b.count), 1);
    el.innerHTML = buckets.map(b => {
        const h = Math.max(4, Math.round((b.count / maxCount) * 80));
        return `<div class="act-session-bar-wrap">
            <div class="act-session-bar" style="height:${h}px" title="${b.label}: ${b.count} sessions"></div>
            <div class="act-session-label">${b.label}</div>
        </div>`;
    }).join('');
}

// ── Heatmap ────────────────────────────────────────────────────────────────
function _renderHeatmap(heatmap) {
    const el    = $('actHeatmapGrid');
    if (!el) return;
    const rows  = heatmap.rows  || [];
    const hours = heatmap.hours || Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));

    if (!rows.length) {
        el.innerHTML = '<div class="empty-state">No heatmap data for selected range</div>';
        return;
    }

    const maxCount = Math.max(...rows.flatMap(r => r.counts || []), 1);
    const _col = count => {
        if (!count) return '#0d1a24';
        const r = count / maxCount;
        return `rgba(30,144,255,${(0.1 + r * 0.75).toFixed(2)})`;
    };

    let html = `<div class="act-heatmap-hours">
        <div class="act-heatmap-row-label"></div>
        ${hours.map(h => `<div class="act-heatmap-hour">${h}</div>`).join('')}
    </div>`;
    rows.forEach(row => {
        html += `<div class="act-heatmap-row">
            <div class="act-heatmap-row-label" title="${row.machine}">${row.machine}</div>
            ${(row.counts || []).map((count, i) =>
                `<div class="act-heatmap-cell" style="background:${_col(count)}" title="${row.machine} ${hours[i]}:00 — ${count} events"></div>`
            ).join('')}
        </div>`;
    });
    el.innerHTML = html;
}

// ── User Activity Timeline ─────────────────────────────────────────────────
function _renderTimeline(timeline) {
    const rowsEl  = $('actTimelineRows');
    const ticksEl = $('actTimelineTicks');
    if (!rowsEl) return;

    const users      = timeline.users  || [];
    const ticks      = timeline.ticks  || [];
    const startMs    = timeline.range_start ? new Date(timeline.range_start).getTime() : 0;
    const endMs      = timeline.range_end   ? new Date(timeline.range_end).getTime()   : Date.now();
    const spanMs     = Math.max(endMs - startMs, 1);

    if (!users.length) {
        rowsEl.innerHTML = '<div class="empty-state">No timeline data for selected range</div>';
        return;
    }

    if (ticksEl && ticks.length) {
        ticksEl.innerHTML = ticks.map(t =>
            `<div class="act-tl-tick" style="left:${t.offset}%">${t.label}</div>`
        ).join('');
    }

    const _stateColor = s => ({
        active:  'rgba(0,230,118,0.4)',
        idle:    'rgba(255,193,7,0.45)',
        locked:  'rgba(255,107,53,0.5)',
        offline: 'rgba(255,56,100,0.3)',
    }[s] || 'rgba(100,120,140,0.3)');

    rowsEl.innerHTML = users.map(u => {
        const blocks = (u.segments || []).map(seg => {
            const s = new Date(seg.start).getTime();
            const e = new Date(seg.end).getTime();
            const left  = Math.max(0, Math.min(100, ((s - startMs) / spanMs) * 100));
            const width = Math.max(0.5, Math.min(100 - left, ((e - s) / spanMs) * 100));
            const startLbl = (seg.start || '').slice(11, 16);
            const endLbl   = (seg.end   || '').slice(11, 16);
            return `<div class="act-tl-block" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;background:${_stateColor(seg.state)}" title="${u.username} — ${seg.state}: ${startLbl}→${endLbl}"></div>`;
        }).join('');
        return `<div class="act-tl-user">
            <div class="act-tl-name" title="${u.username}">${u.username}</div>
            <div class="act-tl-track">${blocks}</div>
        </div>`;
    }).join('');
}

// ── Login Time Distribution Bar Chart ─────────────────────────────────────
function _renderLoginDistChart(distribution) {
    _destroyChart('actLoginDistChart');
    const ctx = document.getElementById('actLoginDistChart');
    if (!ctx) return;

    const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);
    const values = Array.isArray(distribution)
        ? distribution
        : Array.from({ length: 24 }, (_, i) => (distribution[i] || 0));

    // No login events yet — show placeholder instead of empty axes
    if (!values.some(v => v > 0)) {
        const wrap = ctx.parentElement;
        if (wrap) wrap.innerHTML = '<div class="empty-state" style="height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;"><span style="font-size:22px;opacity:0.3;">🕐</span><span style="color:var(--text-3);font-size:11px;">No login events in selected period</span></div>';
        return;
    }

    _charts.actLoginDistChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Logins',
                data: values,
                backgroundColor: 'rgba(0,229,255,0.55)',
                borderColor: '#00e5ff',
                borderWidth: 1,
                borderRadius: 3,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { color: 'rgba(31,53,66,0.7)' },
                    ticks: { color: '#7A8C9A', font: { size: 9 }, maxRotation: 45 },
                },
                y: {
                    min: 0,
                    grid: { color: 'rgba(31,53,66,0.7)' },
                    ticks: { color: '#7A8C9A', font: { size: 10 }, precision: 0 },
                },
            },
        },
    });
}

// ── Application Usage Donut ────────────────────────────────────────────────
function _renderAppDonut(apps) {
    _destroyChart('actAppDonutChart');
    const ctx    = document.getElementById('actAppDonutChart');
    const legend = $('actAppDonutLegend');

    if (!apps.length) {
        const msg = '<div class="empty-state" style="font-size:11px;padding:12px 0;">No app tracking data yet.<br><span style="color:var(--text-3);">Requires APP_USAGE events from agent.</span></div>';
        if (legend) legend.innerHTML = msg;
        // Hide the canvas so it doesn't show as a blank grey box
        if (ctx) ctx.style.display = 'none';
        return;
    }
    // Ensure canvas is visible when data arrives later
    if (ctx) ctx.style.display = '';

    const COLORS = ['#00e5ff', '#00ff9d', '#FFC107', '#FF6B35', '#A855F7', '#FF3864', '#00B8D9', '#64748B'];
    const labels = apps.map(a => a.process_name);
    const values = apps.map(a => a.total_seconds);
    const total  = values.reduce((s, v) => s + v, 0) || 1;

    if (legend) {
        legend.innerHTML = apps.map((a, i) =>
            `<div class="act-app-legend-item">
                <span style="display:flex;align-items:center;gap:6px;">
                    <span style="width:8px;height:8px;border-radius:2px;background:${COLORS[i % COLORS.length]};flex-shrink:0;"></span>
                    <span style="color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px;" title="${a.process_name}">${a.process_name}</span>
                </span>
                <span style="color:var(--text-3);">${a.pct}%</span>
            </div>`
        ).join('');
    }

    if (!ctx) return;
    _charts.actAppDonutChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: COLORS.slice(0, apps.length),
                borderWidth: 0,
                hoverOffset: 6,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '70%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: c => `${c.label}: ${Math.round((c.raw / total) * 100)}%`,
                    },
                },
            },
        },
    });
}

// ── User Productivity Stacked Horizontal Bar ───────────────────────────────
function _renderProductivityChart(users) {
    _destroyChart('actProductivityChart');
    const ctx = document.getElementById('actProductivityChart');
    if (!ctx) return;
    if (!users.length) {
        const wrap = ctx.parentElement;
        if (wrap) wrap.innerHTML = '<div class="empty-state" style="height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;"><span style="font-size:22px;opacity:0.3;">📊</span><span style="color:var(--text-3);font-size:11px;">No session data for selected period</span></div>';
        return;
    }

    const labels     = users.map(u => u.username);
    const activeData = users.map(u => Math.round(u.active_mins));
    const idleData   = users.map(u => Math.round(u.idle_mins));
    const lockData   = users.map(u => Math.round(u.lock_mins));

    _charts.actProductivityChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                { label: 'Active', data: activeData, backgroundColor: 'rgba(0,230,118,0.65)',  stack: 'time' },
                { label: 'Idle',   data: idleData,   backgroundColor: 'rgba(255,193,7,0.65)',  stack: 'time' },
                { label: 'Locked', data: lockData,   backgroundColor: 'rgba(255,107,53,0.65)', stack: 'time' },
            ],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterBody: items => {
                            const u = users[items[0].dataIndex];
                            return u ? [`Score: ${u.productivity_score}%`] : [];
                        },
                    },
                },
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { color: 'rgba(31,53,66,0.7)' },
                    ticks: { color: '#7A8C9A', font: { size: 10 } },
                    title: { display: true, text: 'Minutes', color: '#7A8C9A', font: { size: 10 } },
                },
                y: {
                    stacked: true,
                    grid: { display: false },
                    ticks: { color: '#9FB6C8', font: { size: 11 } },
                },
            },
        },
    });
}

// ── Auto-refresh Timer ─────────────────────────────────────────────────────
function _startAutoRefresh() {
    if (_autoRefreshTimer) clearInterval(_autoRefreshTimer);
    _autoRefreshCountdown = 60;
    _autoRefreshTimer = setInterval(() => {
        _autoRefreshCountdown--;
        const el = $('actRefreshSecs');
        if (el) el.textContent = _autoRefreshCountdown;
        if (_autoRefreshCountdown <= 0) {
            _autoRefreshCountdown = 60;
            _refreshDashboard();
            _loadEventTable(_evtPage);
        }
    }, 1000);
}

export function stopActivityAutoRefresh() {
    if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null; }
}

// ── Event Feed Table ───────────────────────────────────────────────────────
async function _loadEventTable(page = 1) {
    const f  = _getFilters();
    const qs = _toQS({
        machine:   f.machine,
        username:  f.username,
        event:     f.event_type,
        synced:    f.synced,
        search:    f.search,
        date_from: f.date_from,
        date_to:   f.date_to,
        page,
        limit: 20,
    });
    try {
        const data     = await api('GET', `/api/activity/events?${qs}`);
        _evtPage       = data.page  || page;
        _evtTotalPages = data.pages || 1;
        const events   = data.events || [];
        const total    = data.total  || 0;

        const tbody = $('actEventTableBody');
        if (tbody) {
            if (!events.length) {
                tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">No events match the current filters.</div></td></tr>`;
            } else {
                tbody.innerHTML = events.map(ev => {
                    const syncBadge = ev.synced
                        ? `<span style="color:#00E676;font-size:11px;">✔ Synced</span>`
                        : `<span style="color:#FF6B35;font-size:11px;">⏳ Pending</span>`;
                    return `<tr>
                        <td style="color:var(--text-2);font-size:11px;white-space:nowrap;">${_fmtTime(ev.timestamp)}</td>
                        <td style="color:var(--accent);">${ev.username || '—'}</td>
                        <td><span class="machine-tag">${ev.machine || '—'}</span></td>
                        <td style="color:var(--text-3);font-size:11px;">${ev.serial || '—'}</td>
                        <td>${_eventBadge(ev.event)}</td>
                        <td style="color:var(--text-2);">${ev.duration || '—'}</td>
                        <td style="color:var(--text-3);font-size:11px;">${ev.ip_address || '—'}</td>
                        <td>${syncBadge}</td>
                    </tr>`;
                }).join('');
            }
        }

        const info = $('actEvtPageInfo');
        if (info) info.textContent = `${total} total · page ${_evtPage} of ${_evtTotalPages}`;
        const prev = $('actEvtPrev'); if (prev) prev.disabled = _evtPage <= 1;
        const next = $('actEvtNext'); if (next) next.disabled = _evtPage >= _evtTotalPages;
    } catch (err) {
        const tbody = $('actEventTableBody');
        if (tbody) tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">⚠️ ${err.message || 'Failed to load events'}</div></td></tr>`;
    }
}

function _eventBadge(evt) {
    const map = {
        LOGIN:      ['rgba(0,230,118,0.15)',  '#00E676'],
        LOGOUT:     ['rgba(255,56,100,0.15)', '#FF3864'],
        LOCK:       ['rgba(255,107,53,0.15)', '#FF6B35'],
        UNLOCK:     ['rgba(30,144,255,0.15)', '#1E90FF'],
        IDLE:       ['rgba(255,193,7,0.15)',  '#FFC107'],
        ACTIVE:     ['rgba(0,230,118,0.1)',   '#00C963'],
        STARTUP:    ['rgba(130,80,255,0.15)', '#A855F7'],
        SHUTDOWN:   ['rgba(255,56,100,0.18)', '#FF6080'],
        SCREEN_OFF: ['rgba(60,80,100,0.25)',  '#8899AA'],
        SCREEN_ON:  ['rgba(30,144,255,0.1)',  '#66D9EE'],
        APP_USAGE:  ['rgba(0,229,255,0.12)',  '#00e5ff'],
    };
    const [bg, color] = map[evt] || ['rgba(100,120,140,0.15)', '#9FB6C8'];
    return `<span style="background:${bg};color:${color};border:1px solid ${color}44;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;letter-spacing:0.04em;">${evt || '—'}</span>`;
}

function _fmtTime(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString('en-GB', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        });
    } catch { return iso; }
}

// ── Filter Dropdowns ───────────────────────────────────────────────────────
async function _populateDropdowns() {
    try {
        const [mRes, uRes, pRes] = await Promise.allSettled([
            api('GET', '/api/activity/machines'),
            api('GET', '/api/activity/users'),
            api('GET', '/api/activity/processes'),
        ]);
        if (mRes.status === 'fulfilled') {
            const sel = $('actMachine');
            if (sel) {
                const cur = sel.value;
                sel.innerHTML = '<option value="">All Machines</option>';
                (mRes.value.machines || []).forEach(m => {
                    const o = document.createElement('option');
                    o.value = m; o.textContent = m; sel.appendChild(o);
                });
                if (cur) sel.value = cur;
            }
        }
        if (uRes.status === 'fulfilled') {
            const sel = $('actUser');
            if (sel) {
                const cur = sel.value;
                sel.innerHTML = '<option value="">All Users</option>';
                (uRes.value.users || []).forEach(u => {
                    const o = document.createElement('option');
                    o.value = u; o.textContent = u; sel.appendChild(o);
                });
                if (cur) sel.value = cur;
            }
        }
        if (pRes.status === 'fulfilled') {
            const sel = $('actProcess');
            if (sel) {
                const cur = sel.value;
                sel.innerHTML = '<option value="">All Apps</option>';
                (pRes.value.processes || []).forEach(p => {
                    const o = document.createElement('option');
                    o.value = p; o.textContent = p; sel.appendChild(o);
                });
                if (cur) sel.value = cur;
            }
        }
    } catch (e) {
        console.warn('_populateDropdowns failed', e);
    }
}

// ── Public: Period Tabs ────────────────────────────────────────────────────
export function setActivityPeriod(period, el) {
    _period = period;
    document.querySelectorAll('.act-period-tab').forEach(t => t.classList.remove('active'));
    if (el) el.classList.add('active');
    const cr = $('actCustomRange');
    if (cr) cr.style.display = period === 'custom' ? 'flex' : 'none';
    applyActivityFilters();
}

export function applyActivityCustomRange() {
    _customFrom = $('actDateFrom')?.value || '';
    _customTo   = $('actDateTo')?.value   || '';
    applyActivityFilters();
}

// ── Public: Exported API (keeps dashboard.js compatibility) ────────────────
export async function loadActivity(page = 1) {
    _loadEventTable(page);
    _refreshDashboard();
}

export async function loadActivityUsers() { /* handled via loadActivityFilters */ }
export async function loadDeviceSummary() { /* included in analytics */ }
export async function loadHourlyHeatmap() { /* included in analytics */ }
export async function loadUserSummary()   { /* included in analytics */ }
export function  loadSessionTable()       { /* included in analytics */ }

export async function loadActivityKpis() {
    // Lightweight: pull from /api/activity/kpi for KPI cards only
    try {
        const data = await api('GET', '/api/activity/kpi');
        _renderKPIs({
            active:        data.active          ?? 0,
            idle:          data.idle            ?? 0,
            locked:        data.locked          ?? 0,
            offline:       data.offline         ?? 0,
            total_events:  data.total_events    ?? 0,
            sync_health:   data.pending_count != null && data.total_events
                           ? Math.round(((data.total_events - data.pending_count) / data.total_events) * 100)
                           : 100,
        });
    } catch (e) {
        console.warn('loadActivityKpis error', e);
    }
}

export async function loadAnalyticsCharts() {
    await _refreshDashboard();
    await _loadEventTable(_evtPage);
    _startAutoRefresh();
}

export function applyActivityFilters() {
    _refreshDashboard();
    _loadEventTable(1);
}

export function resetActivityFilters() {
    ['actMachine', 'actUser', 'actEventType', 'actSynced', 'actSearch', 'actProcess'].forEach(id => {
        const el = $(id); if (el) el.value = '';
    });
    _period = 'daily';
    document.querySelectorAll('.act-period-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    const cr = $('actCustomRange'); if (cr) cr.style.display = 'none';
    applyActivityFilters();
}

export async function loadActivityFilters() {
    await _populateDropdowns();
}

export function activityPrevPage() {
    if (_evtPage > 1) _loadEventTable(_evtPage - 1);
}
export function activityNextPage() {
    if (_evtPage < _evtTotalPages) _loadEventTable(_evtPage + 1);
}

export function exportActivityCSV() {
    const f  = _getFilters();
    const qs = _toQS({ machine: f.machine, username: f.username, event: f.event_type, synced: f.synced, search: f.search, date_from: f.date_from, date_to: f.date_to, format: 'csv', limit: 10000 });
    window.location.href = `/api/activity/events?${qs}`;
}

export function exportActivityXLSX() {
    const f  = _getFilters();
    const qs = _toQS({ machine: f.machine, username: f.username, event: f.event_type, synced: f.synced, search: f.search, date_from: f.date_from, date_to: f.date_to, format: 'xlsx', limit: 10000 });
    window.location.href = `/api/activity/events?${qs}`;
}

// ── PDF Export ────────────────────────────────────────────────────────────
export async function exportActivityPDF() {
    if (typeof window.jspdf === 'undefined') {
        alert('PDF library not loaded. Please refresh the page.');
        return;
    }
    const f   = _getFilters();
    const qs  = _toQS({ machine: f.machine, username: f.username, date_from: f.date_from, date_to: f.date_to });
    const qs2 = _toQS({ machine: f.machine, username: f.username, event: f.event_type, synced: f.synced, search: f.search, date_from: f.date_from, date_to: f.date_to, limit: 200 });

    const [analyticsRes, appRes, eventsRes] = await Promise.allSettled([
        api('GET', `/api/activity/analytics?${qs}`),
        api('GET', `/api/activity/app-usage?${qs}`),
        api('GET', `/api/activity/events?${qs2}`),
    ]);

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

    // Header band
    doc.setFillColor(8, 12, 16);
    doc.rect(0, 0, 210, 28, 'F');
    doc.setTextColor(0, 229, 255);
    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.text('SentraGuard — Activity Report', 14, 16);
    doc.setTextColor(107, 143, 168);
    doc.setFontSize(9);
    doc.setFont('helvetica', 'normal');
    doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 24);

    let y = 36;

    // KPI summary
    if (analyticsRes.status === 'fulfilled') {
        const kpis = analyticsRes.value.kpis || {};
        doc.autoTable({
            startY: y,
            head: [['Metric', 'Value']],
            body: [
                ['Active Machines',  kpis.active        ?? '—'],
                ['Idle Machines',    kpis.idle          ?? '—'],
                ['Locked Machines',  kpis.locked        ?? '—'],
                ['Offline Devices',  kpis.offline       ?? '—'],
                ['Total Events',     kpis.total_events  ?? '—'],
                ['Sync Health',      kpis.sync_health != null ? `${kpis.sync_health}%` : '—'],
            ],
            theme: 'grid',
            headStyles: { fillColor: [8, 12, 16], textColor: [0, 229, 255], fontSize: 10 },
            bodyStyles: { fontSize: 10 },
        });
        y = doc.lastAutoTable.finalY + 10;
    }

    // App usage
    if (appRes.status === 'fulfilled') {
        const apps = appRes.value.app_breakdown || [];
        if (apps.length) {
            doc.autoTable({
                startY: y,
                head: [['Application', 'Time (s)', 'Share']],
                body: apps.map(a => [a.process_name, a.total_seconds, `${a.pct}%`]),
                theme: 'grid',
                headStyles: { fillColor: [8, 12, 16], textColor: [0, 229, 255], fontSize: 10 },
                bodyStyles: { fontSize: 10 },
            });
            y = doc.lastAutoTable.finalY + 10;
        }
        // Productivity
        const prod = appRes.value.productivity_by_user || [];
        if (prod.length) {
            doc.autoTable({
                startY: y,
                head: [['User', 'Active (min)', 'Idle (min)', 'Locked (min)', 'Score']],
                body: prod.map(u => [u.username, u.active_mins, u.idle_mins, u.lock_mins, `${u.productivity_score}%`]),
                theme: 'grid',
                headStyles: { fillColor: [8, 12, 16], textColor: [0, 229, 255], fontSize: 10 },
                bodyStyles: { fontSize: 10 },
            });
            y = doc.lastAutoTable.finalY + 10;
        }
    }

    // Event log sample
    if (eventsRes.status === 'fulfilled') {
        const evts = eventsRes.value.events || [];
        if (evts.length) {
            doc.autoTable({
                startY: y,
                head: [['Timestamp', 'User', 'Machine', 'Event', 'Duration', 'Synced']],
                body: evts.slice(0, 100).map(e => [
                    _fmtTime(e.timestamp), e.username || '—', e.machine || '—',
                    e.event, e.duration || '—', e.synced ? 'Yes' : 'No',
                ]),
                theme: 'striped',
                headStyles: { fillColor: [8, 12, 16], textColor: [0, 229, 255], fontSize: 9 },
                bodyStyles: { fontSize: 8 },
            });
        }
    }

    doc.save(`sentraguard-activity-${new Date().toISOString().slice(0, 10)}.pdf`);
}

// ── Report Modal ──────────────────────────────────────────────────────────
export async function generateReport(type) {
    const status = $('reportGenStatus');
    if (status) status.textContent = 'Generating report…';

    // Apply preset filters for report type
    const evtSel = $('actEventType');
    if (type === 'app_usage' && evtSel) evtSel.value = 'APP_USAGE';
    else if (type === 'idle' && evtSel) evtSel.value = 'IDLE';
    else if (evtSel) evtSel.value = '';

    if (type === 'daily') {
        _period = 'daily';
        document.querySelectorAll('.act-period-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    } else if (type === 'monthly') {
        _period = 'monthly';
        document.querySelectorAll('.act-period-tab').forEach((t, i) => t.classList.toggle('active', i === 2));
    }

    try {
        await exportActivityPDF();
        if (status) status.textContent = '✔ PDF downloaded.';
    } catch (e) {
        if (status) status.textContent = `⚠ ${e.message || 'Export failed'}`;
    }
    setTimeout(() => { if (status) status.textContent = ''; }, 4000);
}

export function openReportPanel() {
    const m = $('reportPanelModal');
    if (m) m.classList.add('active');
}

export function closeReportPanel() {
    const m = $('reportPanelModal');
    if (m) m.classList.remove('active');
}

// Stubs for backward compat
export function renderStatusRing()      { /* legacy — no-op */ }
export function renderAppUsageBarChart(){ /* legacy — no-op */ }
export async function generateActivityReport() { /* legacy — no-op */ }
