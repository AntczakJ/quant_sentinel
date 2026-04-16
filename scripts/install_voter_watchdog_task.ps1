# install_voter_watchdog_task.ps1 — register voter_watchdog.py every 6h.
#
# Runs `python scripts/voter_watchdog.py --auto-mute --notify` every 6h.
# Must be run once as Administrator.
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "QuantSentinel-VoterWatchdog" -Confirm:$false

$TaskName = "QuantSentinel-VoterWatchdog"
$RepoRoot = "C:\quant_sentinel"
$PythonExe = "$RepoRoot\.venv\Scripts\python.exe"
$Script = "$RepoRoot\scripts\voter_watchdog.py"

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
    -Argument "`"$Script`" --auto-mute --notify" `
    -WorkingDirectory $RepoRoot

# Trigger: every 6 hours, starting now, repeating indefinitely
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 6) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 10)

# UserId needs DOMAIN\USER format on Windows — bare $env:USERNAME fails.
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
        -Description "Quant Sentinel voter accuracy watchdog — every 6h, auto-mutes anti-signal voters + Telegram alert" | Out-Null
} catch {
    Write-Error "Register-ScheduledTask failed: $_"
    exit 1
}

Write-Host ""
Write-Host "[OK] Task '$TaskName' registered (as $FullUser). Runs every 6h."
Write-Host "Test: Start-ScheduledTask -TaskName $TaskName"
