# install_dashboard_task.ps1 - register operator_dashboard daily Telegram cron
#
# Daily 07:30 local task that runs daily_dashboard_telegram.py.
# Builds operator_dashboard MD report + sends compact digest to Telegram.
# Complementary to daily_digest task (which is just trade summary).
#
# Usage (from PowerShell as admin):
#   .\scripts\install_dashboard_task.ps1
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "QuantSentinel-Dashboard" -Confirm:$false

$TaskName = "QuantSentinel-Dashboard"
$RepoRoot = "C:\quant_sentinel"
$PythonExe = "$RepoRoot\.venv\Scripts\python.exe"
$Script = "$RepoRoot\scripts\daily_dashboard_telegram.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at $PythonExe"
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
    -Argument "`"$Script`"" `
    -WorkingDirectory $RepoRoot

# Daily 07:30 — half hour before daily_digest so they don't compete.
$Trigger = New-ScheduledTaskTrigger -Daily -At 07:30

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

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
        -Description "Quant Sentinel operator dashboard daily Telegram digest (07:30)" | Out-Null
} catch {
    Write-Error "Register-ScheduledTask failed: $_"
    exit 1
}

Write-Host ""
Write-Host "[OK] Task '$TaskName' registered. Daily at 07:30."
Write-Host ""
Write-Host "Test now:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
