# Security Log Diagnostic Script
# Must be run as Administrator

$outFile = Join-Path $PSScriptRoot "security_diag_result.txt"

"=== Security Log Diagnostic ===" | Out-File $outFile
"Run at: $(Get-Date)" | Out-File $outFile -Append
"Running as: $env:USERNAME" | Out-File $outFile -Append
"Is Admin: $([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" | Out-File $outFile -Append

try {
    $log = Get-WinEvent -ListLog Security -ErrorAction Stop
    "Log Enabled: $($log.IsEnabled)" | Out-File $outFile -Append
    "Record Count: $($log.RecordCount)" | Out-File $outFile -Append
    "Log Mode: $($log.LogMode)" | Out-File $outFile -Append
    "Max Size (MB): $([math]::Round($log.MaximumSizeInBytes / 1MB, 2))" | Out-File $outFile -Append
} catch {
    "ERROR listing Security log: $_" | Out-File $outFile -Append
}

"`n=== Top 10 Event IDs in Security Log ===" | Out-File $outFile -Append
try {
    $events = Get-WinEvent -LogName Security -MaxEvents 500 -ErrorAction Stop
    "Total events retrieved: $($events.Count)" | Out-File $outFile -Append
    $events | Group-Object Id | Sort-Object Count -Descending | Select-Object -First 10 Name, Count | Format-Table -AutoSize | Out-String | Out-File $outFile -Append
    
    "`n=== Sample of first 5 events ===" | Out-File $outFile -Append
    $events | Select-Object -First 5 Id, TimeCreated, ProviderName | Format-Table -AutoSize | Out-String | Out-File $outFile -Append
    
    "`n=== Looking for login events (4624) ===" | Out-File $outFile -Append
    $logins = $events | Where-Object { $_.Id -eq 4624 }
    "Login events found in sample: $($logins.Count)" | Out-File $outFile -Append
    if ($logins.Count -gt 0) {
        $logins | Select-Object -First 3 Id, TimeCreated | Format-Table -AutoSize | Out-String | Out-File $outFile -Append
    }
    
    "`n=== Looking for logoff events (4634, 4647) ===" | Out-File $outFile -Append
    $logoffs = $events | Where-Object { $_.Id -in @(4634, 4647) }
    "Logoff events found in sample: $($logoffs.Count)" | Out-File $outFile -Append
    
    "`n=== Looking for privilege events (4672) ===" | Out-File $outFile -Append
    $privs = $events | Where-Object { $_.Id -eq 4672 }
    "Privilege events found in sample: $($privs.Count)" | Out-File $outFile -Append

} catch {
    "ERROR reading Security log: $_" | Out-File $outFile -Append
}

"`n=== FilterHashtable Test ===" | Out-File $outFile -Append
try {
    $filtered = Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4624,4625,4634,4647,4648,4672,4778,4779,4800,4801} -MaxEvents 10 -ErrorAction Stop
    "FilterHashtable returned: $($filtered.Count) events" | Out-File $outFile -Append
    $filtered | Select-Object Id, TimeCreated | Format-Table -AutoSize | Out-String | Out-File $outFile -Append
} catch {
    "FilterHashtable ERROR: $_" | Out-File $outFile -Append
}

"=== DONE ===" | Out-File $outFile -Append
