/**
 * features/dashboard.js
 * ── Entry point ──
 * Imports every feature module, bootstraps polling, and exposes all
 * functions on `window` so that onclick="..." attributes in index.html
 * continue to work without modification.
 */

// ── Core ──────────────────────────────────────────────────────────────────
import { checkAuth, loadUserRole, showLogoutModal, hideLogoutModal, performLogout } from '../core/auth.js';
import { hideResult } from '../core/utils.js';

// ── Features ──────────────────────────────────────────────────────────────
import { loadDevices, populateUserDropdown, updateCommandButtons, updateNotifyCount } from './devices.js';
import { checkStatus, grantAdmin, revokeAdmin, openCreateUserModal, closeCreateUserModal, submitCreateUser } from './operations.js';
import { runShellCommand } from './shell.js';
import { openTerminal, closeTerminal } from './terminal.js';
import { refreshAdminList, quickRevoke } from './adminList.js';
import {
    loadHistory, sortBy, changePage, jumpToPage, changeLimit,
    applyFilters, clearFilters, openCmdDetailsModal, closeCmdDetailsModal
} from './history.js';
import {
    loadEventLogs, loadEventLogSummary, applyEventFilters, clearEventFilters,
    changeEventPage, changeEventLimit, jumpToEventPage, sortEventsBy,
    openLogDetailsModal, closeLogDetailsModal
} from './eventLogs.js';
import {
    loadActivity, loadActivityUsers, loadDeviceSummary, loadHourlyHeatmap,
    loadUserSummary, exportActivityCSV, exportActivityXLSX, activityPrevPage, activityNextPage,
    renderStatusRing, renderAppUsageBarChart,
    applyActivityFilters, resetActivityFilters, loadActivityFilters,
    loadActivityKpis, loadAnalyticsCharts, loadSessionTable, generateActivityReport,
    setActivityPeriod, applyActivityCustomRange
} from './activity.js';
import { sendNotification, loadNotifyCampaigns, cancelNotifyCampaign, toggleNotifySchedule } from './notifications.js';
import { openSysInfoModal, closeSysInfoModal, renderSysInfo } from './sysInfo.js';
import { openSoftwareModal, closeSoftwareModal, loadSoftwareInventory } from './software.js';
import { getBitLockerKey, getBitLockerKeyStandalone, closeBitLockerKeyModal } from './bitlocker.js';
import {
    generateOtpForDevice, closeOtpModal, copyOtp,
    renderPatchStatus, loadAgentVersions, uploadAgentVersion, renderVersionTable
} from './maintenance.js';
import { downloadAuditExport } from './audit.js';
import { deleteDeviceFromPortal } from './deleteDevice.js';

// ── Auth ──────────────────────────────────────────────────────────────────
checkAuth();

// ── Expose everything on window for inline onclick= handlers ──────────────
Object.assign(window, {
    // Auth / logout
    showLogoutModal, hideLogoutModal, performLogout,

    // Result box
    hideResult,

    // Devices
    loadDevices, populateUserDropdown, updateCommandButtons, updateNotifyCount,

    // Operations
    checkStatus, grantAdmin, revokeAdmin,
    openCreateUserModal, closeCreateUserModal, submitCreateUser,

    // Shell
    runShellCommand,

    // Terminal
    openTerminal, closeTerminal,

    // Admin list
    refreshAdminList, quickRevoke,

    // History
    loadHistory, sortBy, changePage, jumpToPage, changeLimit,
    applyFilters, clearFilters, openCmdDetailsModal, closeCmdDetailsModal,

    // Event logs
    loadEventLogs, loadEventLogSummary,
    applyEventFilters, clearEventFilters,
    changeEventPage, changeEventLimit, jumpToEventPage, sortEventsBy,
    openLogDetailsModal, closeLogDetailsModal,

    // Activity
    loadActivity, loadActivityUsers, loadDeviceSummary, loadHourlyHeatmap,
    loadUserSummary, exportActivityCSV, exportActivityXLSX, activityPrevPage, activityNextPage,
    renderStatusRing, renderAppUsageBarChart,
    applyActivityFilters, resetActivityFilters, loadActivityFilters,
    loadActivityKpis, loadAnalyticsCharts, loadSessionTable, generateActivityReport,
    setActivityPeriod, applyActivityCustomRange,

    // Notifications
    sendNotification, loadNotifyCampaigns, cancelNotifyCampaign, toggleNotifySchedule,

    // System Info
    openSysInfoModal, closeSysInfoModal, renderSysInfo,

    // Software
    openSoftwareModal, closeSoftwareModal, loadSoftwareInventory,

    // BitLocker
    getBitLockerKey, getBitLockerKeyStandalone, closeBitLockerKeyModal,

    // Maintenance
    generateOtpForDevice, closeOtpModal, copyOtp,
    renderPatchStatus, loadAgentVersions, uploadAgentVersion, renderVersionTable,

    // Audit
    downloadAuditExport,

    // Delete device
    deleteDeviceFromPortal,
});

// ── Polling ────────────────────────────────────────────────────────────────
import { selectedDeviceId } from './devices.js';

async function pollAll() {
    await loadDevices();
    await Promise.allSettled([
        loadHistory(),
        loadEventLogs(),
        loadEventLogSummary(),
        loadNotifyCampaigns(),
        _fetchAllCommandsForDashboard(),
        _fetchAllAdminsCount(),
        // Always refresh KPI cards (Active/Idle/Locked/Offline) regardless of
        // which tab is open so the status badges stay current in real-time.
        loadActivityKpis(),
    ]);

    if (selectedDeviceId) await refreshAdminList();

    const activityView = document.getElementById('view-activity');
    if (activityView && activityView.classList.contains('active')) {
        await Promise.allSettled([
            loadActivity(),
            loadActivityUsers(),
            loadDeviceSummary(),
            loadHourlyHeatmap(),
            loadUserSummary(),
            loadAnalyticsCharts(),
        ]);
        loadSessionTable(true);
    }
    const maintenanceView = document.getElementById('view-maintenance');
    if (maintenanceView && maintenanceView.classList.contains('active')) {
        await loadAgentVersions();
        renderPatchStatus();
    }
}

async function _fetchAllCommandsForDashboard() {
    try {
        const { api } = await import('../core/api.js');
        const data = await api('GET', '/commands/history?limit=10000');
        window._allCommands = data.commands || [];
        if (typeof window.onDashboardDataLoaded === 'function') window.onDashboardDataLoaded();
    } catch (e) {
        console.error('fetchAllCommandsForDashboard error:', e);
    }
}

async function _fetchAllAdminsCount() {
    try {
        const { api } = await import('../core/api.js');
        const devices = window._allDevices || [];
        let count = 0;
        for (const d of devices) {
            const data = await api('GET', `/admin_list/${d.id}`);
            if (data && data.admin_users) count += data.admin_users.length;
        }
        const el = document.getElementById('dash-active-admins');
        if (el) el.textContent = count;
    } catch (e) {
        console.error('fetchAllAdminsCount error', e);
    }
}

// ── Bootstrap ──────────────────────────────────────────────────────────────
loadUserRole();
loadActivityFilters();
pollAll();
setInterval(pollAll, 5000);
