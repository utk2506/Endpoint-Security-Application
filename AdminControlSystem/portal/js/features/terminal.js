/**
 * features/terminal.js
 * Interactive xterm.js WebSocket terminal session.
 */

import { WS_BASE } from '../core/api.js';
import { $, toast } from '../core/utils.js';
import { selectedDeviceId } from './devices.js';

let term             = null;
let terminalSocket   = null;
let termFitAddon     = null;
let termOnDataDisposable = null;

export function openTerminal() {
    if (!selectedDeviceId) { toast('Select a device first', 'error'); return; }

    const modal = $('terminalModal');
    modal.classList.add('show');

    // Always destroy and re-create a fresh terminal instance
    if (term) {
        term.dispose();
        term         = null;
        termFitAddon = null;
    }

    term = new Terminal({
        theme: {
            background: '#0d0d0d',
            foreground: '#f1f5f9',
            cursor:     '#22d3ee',
            selection:  'rgba(34,211,238,0.25)',
            black:      '#0d0d0d',
        },
        fontFamily:   '"Cascadia Code", "Fira Code", "Courier New", monospace',
        fontSize:     14,
        lineHeight:   1.3,
        cursorBlink:  true,
        cursorStyle:  'bar',
        scrollback:   5000,
    });

    termFitAddon = new FitAddon.FitAddon();
    term.loadAddon(termFitAddon);
    term.open($('terminalContainer'));

    function _sendResize() {
        if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN && term) {
            terminalSocket.send(`\x1bPTYR:${term.rows};${term.cols}`);
        }
    }

    requestAnimationFrame(() => {
        termFitAddon.fit();
        term.focus();
        _sendResize();
    });

    const _resizer = () => {
        if (termFitAddon) { termFitAddon.fit(); _sendResize(); }
    };
    window.addEventListener('resize', _resizer);

    if (terminalSocket) { terminalSocket.close(); terminalSocket = null; }

    terminalSocket = new WebSocket(`${WS_BASE}/ws/portal/${selectedDeviceId}`);

    terminalSocket.onopen = () => {
        if (termFitAddon) termFitAddon.fit();
        term.focus();
        _sendResize();
        term.writeln('\x1b[2;36mConnected — session active\x1b[0m');
    };

    let hasReceivedPtyData = false;
    terminalSocket.onmessage = (event) => {
        if (!hasReceivedPtyData) {
            hasReceivedPtyData = true;
            _sendResize();
        }
        term.write(event.data);
        term.scrollToBottom();
    };

    terminalSocket.onclose = () => {
        if (term) term.writeln('\r\n\x1b[31mConnection closed by server.\x1b[0m\r\n');
    };

    terminalSocket.onerror = () => {
        if (term) term.writeln('\r\n\x1b[31mWebSocket error — check server.\x1b[0m\r\n');
    };

    term.onSelectionChange(() => {
        const selection = term.getSelection();
        if (selection) {
            navigator.clipboard.writeText(selection).catch(err => {
                console.warn('Clipboard write failed:', err);
            });
        }
    });

    term.element.addEventListener('contextmenu', async (e) => {
        e.preventDefault();
        try {
            const text = await navigator.clipboard.readText();
            if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN && text) {
                terminalSocket.send(text);
            }
        } catch (err) {
            console.warn('Clipboard read failed:', err);
            toast('Failed to read clipboard', 'error');
        }
    });

    term.attachCustomKeyEventHandler(e => {
        if (e.type === 'keydown' && e.ctrlKey) {
            const key = e.key.toLowerCase();
            if (key === 'c' && term.hasSelection()) return false;
            if (key === 'c' || key === 'x') {
                if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN) {
                    terminalSocket.send('\x03');
                }
                e.preventDefault();
                return false;
            }
        }
        return true;
    });

    termOnDataDisposable = term.onData(data => {
        console.log('xterm keystroke:', JSON.stringify(data));
        
        // Ensure \r becomes \r\n for standard subprocess terminals
        let outbound = data;
        if (outbound === '\r') {
            outbound = '\r\n';
        }

        if (terminalSocket && terminalSocket.readyState === WebSocket.OPEN) {
            terminalSocket.send(outbound);
        }
    });

    modal._resizer = _resizer;
}

export function closeTerminal() {
    const modal = $('terminalModal');
    modal.classList.remove('show');

    if (modal._resizer) {
        window.removeEventListener('resize', modal._resizer);
        modal._resizer = null;
    }
    if (terminalSocket) { terminalSocket.close(); terminalSocket = null; }
    if (term) {
        term.dispose();
        term         = null;
        termFitAddon = null;
    }
}
