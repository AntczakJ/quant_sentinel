# install_api_watchdog_task.ps1 - register api_watchdog.py every 1h.
#
# Runs `python scripts/api_watchdog.py --notify` every hour. External
# health check — fires Telegram alert if the API is down or anomalous.
# Must be run once as Administrator.
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "QuantSentinel-APIWatchdog" -Confirm:$false

$TaskName = "QuantSentinel-APIWatchdog"
$RepoRoot = "C:\quant_sentinel"
$PythonExe = "$RepoRoot\.venv\Scripts\python.exe"
$Script = "$RepoRoot\scripts\api_watchdog.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at $PythonExe."
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Error "Script not found at $Script"
    exit 1
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task $TaskName..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Script`" --notify" `
    -WorkingDirectory $RepoRoot

# Trigger: every 1h for 10 years. [TimeSpan]::MaxValue (P99999999DT...)
# is rejected by Task Scheduler as out-of-range.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# UserId needs DOMAIN\USER format on Windows - bare $env:USERNAME fails.
$FullUser = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $FullUser -LogonType Interactive -RunLevel Limited

$ErrorActionPreference = "Stop"
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Quant Sentinel API watchdog - every 1h, Telegram alert on API down / scanner stale / pnl loss / errors in log" | Out-Null
} catch {
    Write-Error "Register-ScheduledTask failed: $_"
    exit 1
}

Write-Host ""
Write-Host "[OK] Task '$TaskName' registered (as $FullUser). Runs every 1h."
Write-Host "Test: Start-ScheduledTask -TaskName $TaskName"
Write-Host "View last result: Get-ScheduledTaskInfo -TaskName $TaskName"
