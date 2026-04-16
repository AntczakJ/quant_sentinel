# install_daily_digest_task.ps1 — Windows Task Scheduler registration
#
# Registers a daily 08:00 local-time task that runs
# scripts/daily_digest.py. Must be run as Administrator once.
#
# Usage (from PowerShell as admin):
#   .\scripts\install_daily_digest_task.ps1
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "QuantSentinel-DailyDigest" -Confirm:$false

$TaskName = "QuantSentinel-DailyDigest"
$RepoRoot = "C:\quant_sentinel"
$PythonExe = "$RepoRoot\.venv\Scripts\python.exe"
$Script = "$RepoRoot\scripts\daily_digest.py"
$LogFile = "$RepoRoot\logs\daily_digest_cron.log"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at $PythonExe. Did you create the venv?"
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Error "Script not found at $Script"
    exit 1
}

# Remove existing task if present (idempotent)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task $TaskName..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: run python script, redirect output to log
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Script`"" `
    -WorkingDirectory $RepoRoot

# Trigger: daily at 08:00 local time
$Trigger = New-ScheduledTaskTrigger -Daily -At 08:00

# Settings: don't start if on batteries, retry on failure
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# Run as current user (no admin needed for execution once registered).
# UserId needs full DOMAIN\USER or COMPUTERNAME\USER format on Windows —
# bare $env:USERNAME fails with "parameter is incorrect" (20,8):UserId.
$FullUser = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $FullUser -LogonType Interactive -RunLevel Limited

$ErrorActionPreference = "Stop"  # abort on any command failure
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Quant Sentinel daily 24h digest via Telegram (sends summary at 08:00)" | Out-Null
} catch {
    Write-Error "Register-ScheduledTask failed: $_"
    exit 1
}

Write-Host ""
Write-Host "[OK] Task '$TaskName' registered (as $FullUser). Daily at 08:00."
Write-Host "Logs will be written to $LogFile (when task runs)."
Write-Host ""
Write-Host "Test now:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName"
