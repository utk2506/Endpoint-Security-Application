"""
software.py — Installed software inventory collection and push.
"""

import json
import subprocess
import time

from config import SOFTWARE_REFRESH_INTERVAL, CREATE_NO_WINDOW
from logger import log
from network import api_call


def collect_installed_software() -> list:
    """Collect installed software from standard Windows uninstall registry hives."""
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
)

$apps = foreach ($path in $paths) {
    if (Test-Path $path) {
        Get-ChildItem $path | ForEach-Object {
            $name = $_.GetValue('DisplayName')
            if (-not $name) { return }
            $isSystem = $_.GetValue('SystemComponent')
            if ($isSystem -eq 1) { return }
            $parent = $_.GetValue('ParentKeyName')
            if ($parent) { return }
            $release = $_.GetValue('ReleaseType')
            if ($release -and $release -match 'Update|Hotfix') { return }
            [PSCustomObject]@{
                Name            = $name
                Version         = $_.GetValue('DisplayVersion')
                Publisher       = $_.GetValue('Publisher')
                InstallDate     = $_.GetValue('InstallDate')
                UninstallString = $_.GetValue('UninstallString')
            }
        }
    }
}

$apps | Where-Object { $_ } | Sort-Object Name, Version -Unique | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=40,
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            cleaned = []
            for item in data or []:
                name = item.get('Name') or item.get('name')
                if not name:
                    continue
                cleaned.append({
                    "name": name,
                    "version": item.get('Version') or item.get('version'),
                    "publisher": item.get('Publisher') or item.get('publisher'),
                    "install_date": item.get('InstallDate') or item.get('install_date'),
                    "uninstall_string": item.get('UninstallString') or item.get('uninstall_string'),
                })
            return cleaned
    except Exception as e:
        log('WARN', f"collect_installed_software error: {e}")
    return []


def push_software_inventory(server: str, device_id: str) -> None:
    """Collect and push installed software inventory to the server."""
    items = collect_installed_software()
    payload = {"device_id": device_id, "items": items or []}
    resp = api_call(server, 'POST', '/api/v1/device/software', payload)
    if resp and resp.get('status') == 'ok':
        log('INFO', f"✓ Sent software inventory ({resp.get('count', 0)} items)")
    else:
        log('WARN', "Failed to send software inventory")


def software_inventory_thread(server_url: str, device_id: str) -> None:
    """Background thread: sends software inventory on a timer."""
    log('INFO', f"📦 Software inventory sync started (interval: {SOFTWARE_REFRESH_INTERVAL}s)")
    try:
        push_software_inventory(server_url, device_id)
    except Exception as e:
        log('WARN', f"Initial software inventory failed: {e}")

    while True:
        try:
            push_software_inventory(server_url, device_id)
        except Exception as e:
            log('WARN', f"Software inventory error: {e}")
        time.sleep(SOFTWARE_REFRESH_INTERVAL)
