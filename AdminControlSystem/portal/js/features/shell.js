/**
 * features/shell.js
 * Remote shell command execution.
 */

import { api } from '../core/api.js';
import { $, toast } from '../core/utils.js';
import { selectedDeviceId } from './devices.js';
import { loadHistory } from './history.js';

export async function runShellCommand() {
    const payload = $('shellPayload')?.value.trim();
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }
    if (!payload) { toast('Enter a script payload', 'error'); return; }

    try {
        toast('Executing remote shell script…', 'info');
        await api('POST', '/send_command', {
            device_id: selectedDeviceId,
            action: 'shell',
            payload,
        });
        toast('Shell command queued successfully', 'success');
        $('shellPayload').value = '';
        loadHistory();
    } catch (e) {
        toast(e.message, 'error');
    }
}
