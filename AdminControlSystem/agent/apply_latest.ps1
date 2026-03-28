# apply_latest.ps1 — Called hourly by the SentraGuard\ApplyLatest scheduled task (runs as SYSTEM).
# Checks for a newer staged agent binary in the 'updates' subdirectory next to agent.exe,
# stops the service, replaces the binary atomically, then restarts the service.

$ErrorActionPreference = 'SilentlyContinue'

$root    = $PSScriptRoot
$staging = Join-Path $root "updates"
$target  = Join-Path $root "agent.exe"
$logDir  = "$env:ProgramData\SentraGuard"
$flag    = Join-Path $logDir "tray_relaunch.flag"
$log     = Join-Path $logDir "update.log"

# Ensure log directory exists
New-Item -ItemType Directory -Path $logDir -Force -ErrorAction SilentlyContinue | Out-Null

function Write-Log([string]$msg) {
    $ts = Get-Date -Format o
    try { Add-Content -Path $log -Value "$ts`t$msg" -Encoding UTF8 } catch {}
}

Write-Log "ApplyLatest triggered"

# Exit early if staging folder doesn't exist yet
if (-not (Test-Path $staging)) {
    Write-Log "Staging dir not found ($staging); nothing to do."
    exit 0
}

# Find the newest staged binary
$latest = Get-ChildItem (Join-Path $staging "agent-*.exe") -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $latest) {
    Write-Log "No staged binary found in $staging; nothing to do."
    exit 0
}

Write-Log "Applying staged update: $($latest.FullName)"

$ErrorActionPreference = 'Continue'
try {
    # Stop the service gracefully before replacing the binary
    Stop-Service -Name SentraGuard -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    # Also kill any stray agent process (e.g. tray mode)
    Get-Process -Name "agent" -ErrorAction SilentlyContinue | Stop-Process -Force

    Start-Sleep -Seconds 1

    # Replace the binary
    Copy-Item $latest.FullName $target -Force -ErrorAction Stop
    Write-Log "Binary replaced successfully."

    try {
        New-Item -ItemType File -Path $flag -Force -ErrorAction Stop | Out-Null
        Write-Log "Tray relaunch flag created: $flag"
    } catch {
        Write-Log "Failed to create tray flag: $($_.Exception.Message)"
    }

    # Restart the service
    Start-Service -Name SentraGuard -ErrorAction SilentlyContinue
    Write-Log "Service restarted."

    # Remove the staged binary now that it has been applied
    Remove-Item $latest.FullName -Force -ErrorAction SilentlyContinue
    Write-Log "Staged binary removed. Update complete."
    exit 0
} catch {
    Write-Log "Update failed: $($_.Exception.Message)"
    # Always try to ensure the service is back up
    Start-Service -Name SentraGuard -ErrorAction SilentlyContinue
    exit 1
}
