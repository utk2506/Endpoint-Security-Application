/**
 * features/bitlocker.js
 * BitLocker key retrieval (from sysinfo cache or live agent command) and display modal.
 */

import { api } from '../core/api.js';
import { toast } from '../core/utils.js';
import { selectedDeviceId, _deviceCache } from './devices.js';

export async function getBitLockerKey(deviceId, driveLetter) {
    try {
        console.log(`[getBitLockerKey] Fetching key for Device ID: ${deviceId}, Drive: ${driveLetter}`);

        const targetId = (deviceId && deviceId !== 'undefined') ? deviceId : selectedDeviceId;
        if (!targetId) { toast('No device context found. Please re-select the device.', 'error'); return; }

        const cachedDevice = _deviceCache.find(d => d.id == targetId);
        if (!cachedDevice || !cachedDevice.system_info) {
            console.error('[getBitLockerKey] Device not found in cache for ID:', targetId);
            toast('Device data not available in cache. Try clicking Refresh.', 'error');
            return;
        }

        const infoStr = cachedDevice.system_info;
        const info    = (typeof infoStr === 'string' && infoStr !== 'null') ? JSON.parse(infoStr) : (infoStr || {});
        const disks   = Array.isArray(info.disks) ? info.disks : (info.disks ? [info.disks] : []);
        const targetDisk = disks.find(d => d.drive === driveLetter);

        if (!targetDisk) { toast(`Drive ${driveLetter} not found on this device`, 'error'); return; }

        const recoveryKey = targetDisk.recovery_key;
        if (!recoveryKey || recoveryKey === 'Not Encrypted' || recoveryKey === 'Not encrypted') {
            toast(`Drive ${driveLetter} is not BitLocker encrypted`, 'info');
        } else if (
            recoveryKey === 'Not found' ||
            recoveryKey.startsWith('Failed') ||
            (typeof recoveryKey === 'string' && recoveryKey.includes('Key not found'))
        ) {
            toast('Requesting live BitLocker key from agent...', 'info');
            try {
                const res   = await api('POST', '/send_command', { device_id: targetId, action: 'get_bitlocker_key', payload: driveLetter });
                const cmdId = res.command_id;
                toast('Command sent! Waiting for agent to respond...', 'info');

                let attempts   = 0;
                const maxAttempts = 20;
                const pollTimer = setInterval(async () => {
                    attempts++;
                    try {
                        const hist = await api('GET', `/commands/history?device_id=${encodeURIComponent(targetId)}&action=get_bitlocker_key&limit=5`);
                        if (hist && hist.commands) {
                            const cmd = hist.commands.find(c => c.id === cmdId);
                            if (cmd && (cmd.status === 'completed' || cmd.status === 'failed')) {
                                clearInterval(pollTimer);
                                if (cmd.status === 'completed') {
                                    toast('BitLocker key retrieved successfully!', 'success');
                                    _showKeyModal(cachedDevice.hostname, driveLetter, cmd.result || 'Unknown result');
                                } else {
                                    toast(`Agent failed to retrieve key: ${cmd.result}`, 'error');
                                }
                                return;
                            }
                        }
                    } catch (e) { console.error('Poll error', e); }

                    if (attempts >= maxAttempts) {
                        clearInterval(pollTimer);
                        toast('Timed out waiting for agent. Please check Command History later.', 'warning');
                    }
                }, 1500);
            } catch (err) {
                toast(`Failed to send request: ${err.message}`, 'error');
            }
        } else {
            _showKeyModal(cachedDevice.hostname, driveLetter, recoveryKey);
        }
    } catch (e) {
        console.error('[getBitLockerKey] Error:', e);
        toast('Error reading key data', 'error');
    }
}

function _showKeyModal(hostname, drive, key) {
    document.getElementById('bkModalDevice').textContent = hostname;
    document.getElementById('bkModalDrive').textContent  = drive;
    document.getElementById('bkModalKey').textContent    = key;
    document.getElementById('bitlockerKeyModal').classList.add('show');
}

export function closeBitLockerKeyModal() {
    document.getElementById('bitlockerKeyModal').classList.remove('show');
}

export function getBitLockerKeyStandalone() {
    const deviceId = document.getElementById('bitlockerDevice')?.value || selectedDeviceId || document.getElementById('deviceSelect')?.value;
    if (!deviceId) { toast('Select a target device first', 'error'); return; }

    const driveInput = document.getElementById('bitlockerDrive');
    let drive = (driveInput?.value || '').trim().toUpperCase();
    if (!drive) { toast('Enter a drive letter (e.g. C:)', 'error'); return; }
    if (drive.length === 1) drive += ':';

    getBitLockerKey(deviceId, drive);
    if (driveInput) driveInput.value = '';
}
