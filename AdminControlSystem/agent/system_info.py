"""
system_info.py — Hardware/OS telemetry, BitLocker keys, user account enumeration.
"""

import json
import platform
import re
import socket
import subprocess

from config import CREATE_NO_WINDOW, CREATE_DEFAULT_ERROR_MODE, _recovery_keys_cache
from logger import log
from network import powershell_available


# ── Network identity ──────────────────────────────────────────────────────────

def get_hostname() -> str:
    return platform.node() or socket.gethostname()


def get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ── BitLocker ─────────────────────────────────────────────────────────────────

def execute_get_bitlocker_key(drive_letter: str, dry_run: bool = False):
    """Retrieve BitLocker recovery key for a drive using manage-bde."""
    if not drive_letter:
        return False, "Drive letter required"

    drive = drive_letter.strip().upper()
    if len(drive) == 1:
        drive += ':'

    cmd = ['manage-bde', '-protectors', '-get', drive, '-type', 'RecoveryPassword']

    if dry_run:
        log('DRY-RUN', f"Would run: {' '.join(cmd)}")
        return True, "Dry-run: recovery key command would be executed"

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20,
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            log('INFO', f"✓ BitLocker key retrieved for {drive}")
            return True, result.stdout
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, f"BitLocker error: {err}"
    except Exception as e:
        log('WARN', f"execute_get_bitlocker_key error: {e}")
        return False, f"Execution error: {str(e)}"


# ── Full system info ───────────────────────────────────────────────────────────

_PS_SYSTEM_INFO = r"""
$ErrorActionPreference = 'SilentlyContinue'

$os       = Get-WmiObject Win32_OperatingSystem
$upSec    = (New-TimeSpan -Start $os.ConvertToDateTime($os.LastBootUpTime) -End (Get-Date)).TotalSeconds
$upFmt    = "$([int]($upSec/3600))h $([int](($upSec%3600)/60))m"
$freeGB   = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totalGB  = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)

$cpu      = Get-WmiObject Win32_Processor | Select-Object -First 1
$cpuLoad  = (Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average

$disksRaw = Get-WmiObject Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $drive = $_.DeviceID
    $blRaw = manage-bde -status $drive 2>$null
    $bl = ($blRaw | Out-String)

    $perc = 'N/A'
    if ($bl -match 'Percentage Encrypted:\s+([\d\.]+\s*%)') { $perc = $matches[1].Trim() }

    $prot = 'Unknown'
    if ($bl -match 'Protection Status:\s+Protection\s+(On|Off)') { $prot = $matches[1] }
    elseif ($bl -match 'Protection Status:\s+(\w+)') { $prot = $matches[1] }

    $conv = 'Unknown'
    if ($bl -match 'Conversion Status:\s+(.+)') { $conv = $matches[1].Trim() }

    @{
        drive       = $drive
        size_gb     = [math]::Round($_.Size / 1GB, 2)
        free_gb     = [math]::Round($_.FreeSpace / 1GB, 2)
        bitlocker   = "$perc (Protection $prot)"
        bl_status   = $conv
    }
}

$cs   = Get-WmiObject Win32_ComputerSystem
$bios = Get-WmiObject Win32_BIOS

$nics = Get-WmiObject Win32_NetworkAdapter -Filter "PhysicalAdapter=True and MACAddress IS NOT NULL" | ForEach-Object {
    $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "Index=$($_.Index)"
    $ip = $null
    if ($cfg -and $cfg.IPAddress) {
        $ip = ($cfg.IPAddress | Where-Object { $_ -notmatch ':' } | Select-Object -First 1)
    }
    @{ description = $_.Name; mac = $_.MACAddress; ip = $ip }
}

@{
    hostname        = $env:COMPUTERNAME
    logged_user     = $cs.UserName
    os_name         = $os.Caption
    os_version      = $os.Version
    os_arch         = $os.OSArchitecture
    uptime          = $upFmt
    cpu_name        = $cpu.Name.Trim()
    cpu_cores       = $cpu.NumberOfCores
    cpu_load_pct    = $cpuLoad
    ram_total_gb    = $totalGB
    ram_free_gb     = $freeGB
    ram_used_pct    = [math]::Round((($totalGB - $freeGB) / $totalGB) * 100, 1)
    disks           = @($disksRaw)
    manufacturer    = $cs.Manufacturer
    model           = $cs.Model
    serial_number   = $bios.SerialNumber
    bios_version    = $bios.SMBIOSBIOSVersion
    network         = @($nics)
} | ConvertTo-Json -Depth 4 -Compress
"""


def collect_system_info():
    """Collect hardware & OS telemetry using a single PowerShell script."""
    if not powershell_available():
        return {
            "os": platform.platform(),
            "hostname": get_hostname(),
            "ip": get_ip(),
        }
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS_SYSTEM_INFO],
            capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW | CREATE_DEFAULT_ERROR_MODE,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())

            # Auto-fetch BitLocker recovery keys for encrypted drives
            for disk in data.get('disks', []):
                drive = disk.get('drive', '')
                bl_status = str(disk.get('bitlocker', ''))
                is_encrypted = (
                    'Protection On' in bl_status
                    or ('%' in bl_status and not bl_status.startswith('0%') and not bl_status.startswith('N/A'))
                )
                if is_encrypted:
                    if drive not in _recovery_keys_cache:
                        log('INFO', f"Auto-fetching recovery key for {drive}...")
                        success, out = execute_get_bitlocker_key(drive)
                        if success:
                            match = re.search(r'Password:\s*([0-9-]{55})', out)
                            _recovery_keys_cache[drive] = match.group(1).strip() if match else "Key not found in output"
                        else:
                            _recovery_keys_cache[drive] = "Failed to fetch key"
                    disk['recovery_key'] = _recovery_keys_cache.get(drive, "Not found")
                else:
                    disk['recovery_key'] = "Not Encrypted"

            log('INFO', f"✓ System info collected (CPU: {data.get('cpu_name','?')}, RAM: {data.get('ram_total_gb','?')} GB)")
            return data
        else:
            log('WARN', f"System info PowerShell failed: {result.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        log('WARN', "System info collection timed out")
    except Exception as e:
        log('WARN', f"System info error: {e}")
    return None


# ── User account list ─────────────────────────────────────────────────────────

def collect_all_users() -> list:
    """Collect all local user accounts via PowerShell Get-LocalUser."""
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$users = Get-LocalUser | Select-Object Name, Enabled | ForEach-Object {
    @{ name = $_.Name; enabled = [bool]$_.Enabled }
}
@($users) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            return data or []
    except Exception as e:
        log('WARN', f"collect_all_users error: {e}")
    return []
