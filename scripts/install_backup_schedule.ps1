# scripts/install_backup_schedule.ps1
# Register Windows Task Scheduler entry for daily off-host backup at 03:00.
# Run ONCE (idempotent — re-running updates the existing task).
#
# Usage (in PowerShell):
#   .\scripts\install_backup_schedule.ps1
#
# Verify after install:
#   Get-ScheduledTask -TaskName "QuantSentinelBackup"
#   Get-ScheduledTaskInfo -TaskName "QuantSentinelBackup"
#
# To remove:
#   Unregister-ScheduledTask -TaskName "QuantSentinelBackup" -Confirm:$false

$ErrorActionPreference = "Stop"
$TaskName = "QuantSentinelBackup"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$ScriptPath = Join-Path $RepoRoot "scripts\offhost_backup_sync.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Backup script not found at $ScriptPath"
    exit 1
}

Write-Host "Installing scheduled task '$TaskName'" -ForegroundColor Cyan
Write-Host "  Script: $ScriptPath"
Write-Host "  Trigger: Daily 03:00"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At 03:00

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Remove existing task if present (idempotent install)
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "  Existing task found - replacing" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Quant Sentinel - daily off-host backup via rclone"

Write-Host "Installed." -ForegroundColor Green
Write-Host ""
Write-Host "Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Next run:" -ForegroundColor Cyan
$NextRun = (Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo).NextRunTime
Write-Host "  $NextRun"
