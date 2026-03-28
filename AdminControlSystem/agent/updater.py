"""
updater.py — Auto-update loop: version check, binary download, and atomic swap via PowerShell.
"""

import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from config import (
    AGENT_VERSION, SWAP_LOCK_FILE, UPDATE_STAGING_DIR,
    UPDATE_MIN_INTERVAL, UPDATE_MAX_INTERVAL,
    DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP,
)
from logger import log
from network import api_call, AGENT_AUTH_TOKEN, download_binary
from state import compute_sha256, ensure_dir, load_state, save_state, update_state


# ── Path helpers ──────────────────────────────────────────────────────────────

def current_binary_path() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()


def resolve_install_root(cli_install_dir: "str | None" = None) -> Path:
    from config import DEFAULT_INSTALL_DIR
    if cli_install_dir:
        return Path(cli_install_dir)
    env_dir = os.environ.get("ACS_INSTALL_DIR")
    if env_dir:
        return Path(env_dir)
    from state import runtime_root
    runtime = runtime_root()
    if "Program Files" in str(runtime):
        return runtime
    return Path(DEFAULT_INSTALL_DIR)


def staging_dir_path(install_root: Path) -> Path:
    path = install_root / UPDATE_STAGING_DIR
    ensure_dir(path)
    return path


# ── Binary swap ───────────────────────────────────────────────────────────────

def schedule_binary_swap(staged_path: Path, service_name: str, server_url: "str | None" = None) -> None:
    """Swap the current binary with the staged one via a detached PowerShell helper."""
    target = current_binary_path()
    backup = target.with_name(f"{target.stem}_old_{int(time.time())}{target.suffix}")
    helper = staged_path.with_suffix(".ps1")
    server_url = server_url or "https://localhost:8000"
    lock_file = target.parent / SWAP_LOCK_FILE
    try:
        lock_file.touch()
    except Exception:
        pass

    script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
$source   = '{staged_path}'
$target   = '{target}'
$backup   = '{backup}'
$lock     = '{lock_file}'
$service  = '{service_name}'
$server   = '{server_url}'
$serviceNames = @($service) | Where-Object {{ $_ -and (Get-Service -Name $_ -ErrorAction SilentlyContinue) }}
$procName = [System.IO.Path]::GetFileNameWithoutExtension($target)
$log      = Join-Path (Split-Path $target) "agent_swap.log"
$log2     = Join-Path "$env:ProgramData\\SentraGuard" "agent_swap.log"
$log3     = Join-Path $env:TEMP "agent_swap.log"
$root     = Split-Path $target
$flagDir  = Join-Path $env:ProgramData "SentraGuard"
$flag     = Join-Path $flagDir "tray_relaunch.flag"
$applyPs1 = Join-Path $root "apply_latest.ps1"
$applyTask = "SentraGuard\\ApplyLatest"
New-Item -ItemType Directory -Path (Split-Path $log) -Force -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType Directory -Path (Split-Path $log2) -Force -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType Directory -Path (Split-Path $log3) -Force -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType Directory -Path $flagDir -Force -ErrorAction SilentlyContinue | Out-Null

function Write-Log([string]$msg) {{
    $ts = Get-Date -Format o
    try {{ Add-Content -Path $log -Value "$ts`t$msg" -Encoding UTF8 }} catch {{}}
    try {{ Add-Content -Path $log2 -Value "$ts`t$msg" -Encoding UTF8 }} catch {{}}
    try {{ Add-Content -Path $log3 -Value "$ts`t$msg" -Encoding UTF8 }} catch {{}}
}}

Write-Log "Swap starting: source=$source target=$target"

Get-ChildItem (Split-Path $target) -Filter "$procName`_old_*" | ForEach-Object {{
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}}

$copied = $false
$altTargets = @()
try {{ $pf = $env:ProgramFiles; if ($pf) {{ $altTargets += (Join-Path $pf 'SentraGuard\\agent.exe') }} }} catch {{}}
try {{ $pfx = ${{env:ProgramFiles(x86)}}; if ($pfx) {{ $altTargets += (Join-Path $pfx 'SentraGuard\\agent.exe') }} }} catch {{}}
$altTargets = $altTargets | Select-Object -Unique | Where-Object {{ $_ -and ($_ -ne $target) }}
$ErrorActionPreference = 'Continue'

for ($i = 0; $i -lt 15; $i++) {{
    foreach ($svc in $serviceNames) {{ Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue }}
    Get-Process -Name $procName -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    try {{
        Copy-Item $target $backup -Force -ErrorAction Stop
        Copy-Item $source $target -Force -ErrorAction Stop
        foreach ($alt in $altTargets) {{
            try {{ Copy-Item $source $alt -Force -ErrorAction Stop; Write-Log "Synced alt: $alt" }}
            catch {{ Write-Log "Failed alt $alt: $($_.Exception.Message)" }}
        }}
        $copied = $true
        Write-Log "Swap succeeded on attempt $i"
        break
    }} catch {{ Write-Log "Attempt $i failed: $($_.Exception.Message)" }}
}}

$ErrorActionPreference = 'SilentlyContinue'

if ($copied) {{
    # Remove the swap lock BEFORE restarting, so the new binary does not see a stale lock
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    Write-Log "Swap lock removed"
    try {{
        New-Item -ItemType File -Path $flag -Force -ErrorAction Stop | Out-Null
        Write-Log "Tray relaunch flag created: $flag"
    }} catch {{ Write-Log "Failed to create tray flag: $($_.Exception.Message)" }}

    foreach ($svc in $serviceNames) {{ Start-Service -Name $svc -ErrorAction SilentlyContinue }}
    if (-not $serviceNames) {{ Start-Process -FilePath $target; Write-Log "Started agent directly" }}
    Write-Log "Service(s) restarted: $($serviceNames -join ', ')"

    try {{
        $runKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
        Set-ItemProperty -Path $runKey -Name 'SentraGuardTray' -Value ("`"$target`" --tray --server=$server --no-verify-ssl") -Type String -Force
        Write-Log "Tray registry autostart key ensured"
    }} catch {{ Write-Log "Failed registry key: $($_.Exception.Message)" }}

    # ── Self-healing tray task (Interactive logon type = user desktop session) ────
    try {{
        $exp = Get-Process -Name explorer -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($exp) {{
            $owner    = (Get-CimInstance Win32_Process -Filter "ProcessId=$($exp.Id)").GetOwner()
            $trayUser = if ($owner.Domain) {{ "$($owner.Domain)\$($owner.User)" }} else {{ $owner.User }}
            Get-Process -Name $procName -ErrorAction SilentlyContinue |
                Where-Object {{ $_.SessionId -ne 0 }} |
                Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Log "Cleared stale user-session processes"
        $action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"Start-Process -FilePath '\""$target\""' -ArgumentList '\"'\"'--tray --server=$server --no-verify-ssl'\"'\"' -WindowStyle Hidden`"")
        $tLogon    = New-ScheduledTaskTrigger -AtLogOn -User $trayUser
        $tRepeat   = New-ScheduledTaskTrigger -Once -At (Get-Date "2000-01-01 00:00") -RepetitionInterval (New-TimeSpan -Minutes 2)
        $settings  = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -DisallowStartIfOnBatteries $false -StopIfGoingOnBatteries $false
        $principal = New-ScheduledTaskPrincipal -UserId $trayUser -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskName "SentraGuardTray" -Action $action -Trigger @($tLogon,$tRepeat) -Settings $settings -Principal $principal -Force | Out-Null
            Write-Log "Tray task registered for user=$trayUser (Interactive, 2-min self-heal)"
            Start-Sleep -Seconds 5
            Start-ScheduledTask -TaskName "SentraGuardTray"
            Write-Log "Tray task started for $trayUser"
        }} else {{
            Write-Log "No explorer process — cannot determine interactive user"
        }}
    }} catch {{ Write-Log "Tray task error: $($_.Exception.Message)" }}

    Remove-Item $source -Force -ErrorAction SilentlyContinue
}} else {{
    Write-Log "Swap failed after retries; staged binary kept for retry"
    # Still remove the lock even on failure so the agent is not permanently frozen
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    Write-Log "Swap lock removed (failure path)"
}}

Remove-Item $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
    try:
        helper.write_text(script, encoding="utf-8")
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        log("INFO", "Update helper launched; exiting for binary swap…")
        os._exit(0)
    except Exception as e:
        log("ERROR", f"Failed to launch update helper: {e}")


# ── Update polling loop ───────────────────────────────────────────────────────

def update_poll_loop(server_url: str, device_id: str, service_name: str, install_root: Path) -> None:
    """Background loop: check for newer agent version and apply via binary swap."""
    staging = staging_dir_path(install_root)
    update_state(update_available=False, latest_version=AGENT_VERSION)

    while True:
        wait_s = random.randint(UPDATE_MIN_INTERVAL, UPDATE_MAX_INTERVAL)
        for _ in range(wait_s):
            time.sleep(1)
            state = load_state()
            if state.get("force_update_check"):
                state.pop("force_update_check", None)
                save_state(state)
                break

        try:
            resp_data = api_call(server_url, "GET", f"/agent/version?device_id={device_id}&current_version={AGENT_VERSION}")
            server_version = resp_data.get("version") if isinstance(resp_data, dict) else None
            update_flagged = isinstance(resp_data, dict) and bool(resp_data.get("update_available"))

            if not update_flagged and server_version == AGENT_VERSION:
                update_state(update_available=False, latest_version=server_version or AGENT_VERSION, swap_in_progress=False)
                continue
            if not isinstance(resp_data, dict):
                continue

            download_url = cast(str, resp_data.get("download_url"))
            checksum = cast(str, resp_data.get("checksum_sha256"))
            new_version = cast(str, resp_data.get("version"))

            if new_version == AGENT_VERSION:
                log("INFO", f"Agent already at latest version ({AGENT_VERSION}); skipping update.")
                update_state(update_available=False, latest_version=new_version)
                continue
            if not download_url or not new_version:
                update_state(update_available=False, latest_version=AGENT_VERSION, swap_in_progress=False)
                continue

            update_state(update_available=True, latest_version=new_version)
            _raw_name = download_url.split("/")[-1].split("?")[0]
            file_name = _raw_name if _raw_name.lower().endswith(".exe") else f"agent-{new_version}.exe"
            staged_path = staging / file_name

            if staged_path.exists() and checksum:
                actual = compute_sha256(staged_path)
                if actual.lower() == checksum.lower() and new_version != AGENT_VERSION:
                    log("INFO", f"Update {new_version} already staged; proceeding to swap.")
                    schedule_binary_swap(staged_path, service_name, server_url)
                    continue

            log("INFO", f"⬇ Downloading agent update {new_version}…")
            download_binary(download_url, staged_path)
            if checksum:
                actual = compute_sha256(staged_path)
                if actual.lower() != checksum.lower():
                    log("ERROR", f"Checksum mismatch: expected {checksum}, got {actual}")
                    staged_path.unlink(missing_ok=True)
                    continue

            log("INFO", f"Update {new_version} ready; scheduling binary swap.")
            update_state(update_available=False, latest_version=new_version, swap_in_progress=True)
            schedule_binary_swap(staged_path, service_name, server_url)
        except Exception as e:
            log("WARN", f"Version check/apply failed: {e}")
