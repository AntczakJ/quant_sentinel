# scripts/install_api_restart_schedule.ps1
# Sunday 04:00 weekly API restart — memory cleanup, prevent stale state.
# Idempotent — re-running replaces existing.

$ErrorActionPreference = "Continue"
$TaskName = "QuantSentinelAPIRestart"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$RestartScript = Join-Path $RepoRoot "scripts\restart_api.ps1"

# Create the restart script if it doesn't exist
if (-not (Test-Path $RestartScript)) {
    @"
# scripts/restart_api.ps1 — kill old uvicorn + start fresh
`$ErrorActionPreference = 'Continue'
Set-Location '$RepoRoot'

# Find and kill existing uvicorn
Get-Process | Where-Object {`$_.CommandLine -match 'uvicorn api.main'} | ForEach-Object {
    Stop-Process -Id `$_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 4

# Start fresh
Start-Process -FilePath '.venv\Scripts\python.exe' ``
    -ArgumentList '-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8000','--log-level','info' ``
    -WorkingDirectory '$RepoRoot' ``
    -WindowStyle Hidden ``
    -RedirectStandardOutput 'logs\api.log' ``
    -RedirectStandardError 'logs\api.err.log'

Add-Content -Path 'logs\api_restart.log' -Value "`$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK') restart OK"
"@ | Set-Content -Path $RestartScript -Encoding utf8
    Write-Host "Created restart script at $RestartScript" -ForegroundColor Cyan
}

Write-Host "Installing '$TaskName' (Sundays 04:00)" -ForegroundColor Cyan

$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RestartScript`""
$schResult = cmd.exe /c "schtasks /Create /TN $TaskName /TR ""$cmd"" /SC WEEKLY /D SUN /ST 04:00 /RL LIMITED /F 2>&1"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Installed." -ForegroundColor Green
    Write-Host ""
    Write-Host "Verify with:" -ForegroundColor Cyan
    Write-Host "  schtasks /Query /TN $TaskName"
} else {
    Write-Host "schtasks failed (exit $LASTEXITCODE):" -ForegroundColor Red
    Write-Host $schResult
    exit 1
}
