/**
 * features/deleteDevice.js
 * Permanently delete an uninstalled device record from the portal.
 */

import { api } from '../core/api.js';
import { toast } from '../core/utils.js';
import { loadDevices } from './devices.js';

export async function deleteDeviceFromPortal(deviceId, hostname) {
    if (!confirm(`Permanently delete "${hostname}" from the portal?\n\nThis cannot be undone. The device record, command history, and event logs will all be removed.`)) return;
    try {
        await api('DELETE', `/devices/${deviceId}`);
        toast(`Device "${hostname}" has been permanently removed.`, 'success');
        await loadDevices();
    } catch (e) {
        toast(`Failed to delete: ${e.message}`, 'error');
    }
}
