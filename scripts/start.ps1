<#
.SYNOPSIS
    One-touch starter for Quant Sentinel API + frontend dev server.

.DESCRIPTION
    Wraps the long uvicorn / vite incantations into a short
    `.\scripts\start.ps1 <command>` interface. Each command is
    idempotent — if the target port is already serving, the script
    does nothing instead of double-spawning.

.EXAMPLE
    .\scripts\start.ps1 api      # uvicorn on :8000 (background, log → logs/api.log)
    .\scripts\start.ps1 dev      # vite frontend on :5173
    .\scripts\start.ps1 both     # both, sequentially
    .\scripts\start.ps1 stop     # kills both
    .\scripts\start.ps1 status   # what's running on :8000 and :5173
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('api', 'dev', 'both', 'stop', 'status', 'restart')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Get-PortPid([int]$Port) {
    $line = (netstat -ano | Select-String ":$Port\s.*LISTENING")
    if ($line) {
        return ($line.ToString().Trim() -split '\s+')[-1]
    }
    return $null
}

function Stop-PortPid([int]$Port, [string]$Label) {
    $portPid = Get-PortPid $Port
    if ($portPid) {
        Write-Host "Stopping $Label (PID $portPid on :$Port)..." -ForegroundColor Yellow
        taskkill /F /PID $portPid 2>&1 | Out-Null
        Start-Sleep -Seconds 1
    } else {
        Write-Host "$Label not running on :$Port" -ForegroundColor DarkGray
    }
}

function Start-Api {
    $existing = Get-PortPid 8000
    if ($existing) {
        Write-Host "API already running on :8000 (PID $existing) — skipping." -ForegroundColor DarkGray
        return
    }
    Write-Host "Starting API (uvicorn :8000) → logs/api.log" -ForegroundColor Green
    Push-Location $root
    try {
        $py = Join-Path $root '.venv\Scripts\python.exe'
        if (-not (Test-Path $py)) {
            Write-Host "ERROR: .venv not found at $py" -ForegroundColor Red
            return
        }
        # Detached background — won't die when this PowerShell window closes.
        $logsDir = Join-Path $root 'logs'
        if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
        $logFile = Join-Path $logsDir 'api.log'
        Start-Process -FilePath $py `
            -ArgumentList '-m', 'uvicorn', 'api.main:app',
                          '--host', '127.0.0.1', '--port', '8000',
                          '--log-level', 'info' `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError "$logFile.err" `
            -WindowStyle Hidden `
            -WorkingDirectory $root | Out-Null
        Start-Sleep -Seconds 2
        $newPid = Get-PortPid 8000
        if ($newPid) {
            Write-Host "API up — PID $newPid" -ForegroundColor Green
        } else {
            Write-Host "API did not bind :8000 within 2s, check $logFile" -ForegroundColor Red
        }
    } finally {
        Pop-Location
    }
}

function Start-Dev {
    $existing = Get-PortPid 5173
    if ($existing) {
        Write-Host "Frontend dev already running on :5173 (PID $existing) — skipping." -ForegroundColor DarkGray
        return
    }
    Write-Host "Starting frontend dev (vite :5173)" -ForegroundColor Green
    $frontendDir = Join-Path $root 'frontend'
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Write-Host "node_modules missing — running npm install first..." -ForegroundColor Yellow
        Push-Location $frontendDir
        try { & npm install } finally { Pop-Location }
    }
    Push-Location $frontendDir
    try {
        Start-Process -FilePath 'npm.cmd' `
            -ArgumentList 'run', 'dev' `
            -WindowStyle Hidden `
            -WorkingDirectory $frontendDir | Out-Null
        Start-Sleep -Seconds 3
        $newPid = Get-PortPid 5173
        if ($newPid) {
            Write-Host "Vite up — PID $newPid · http://127.0.0.1:5173" -ForegroundColor Green
        } else {
            Write-Host "Vite did not bind :5173 within 3s" -ForegroundColor Red
        }
    } finally {
        Pop-Location
    }
}

function Show-Status {
    $apiPid = Get-PortPid 8000
    $devPid = Get-PortPid 5173
    Write-Host ""
    Write-Host ("API     :8000   {0}" -f $(if ($apiPid) { "UP (PID $apiPid)" } else { "DOWN" })) `
        -ForegroundColor $(if ($apiPid) { 'Green' } else { 'DarkGray' })
    Write-Host ("Vite    :5173   {0}" -f $(if ($devPid) { "UP (PID $devPid)" } else { "DOWN" })) `
        -ForegroundColor $(if ($devPid) { 'Green' } else { 'DarkGray' })
    if ($apiPid) {
        $health = $null
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        } catch { }
        if ($health) {
            Write-Host ("        health: {0}, models_loaded: {1}, uptime: {2}" -f `
                $health.status, $health.models_loaded, $health.uptime) -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

switch ($Command) {
    'api'     { Start-Api }
    'dev'     { Start-Dev }
    'both'    { Start-Api; Start-Dev; Show-Status }
    'stop'    { Stop-PortPid 8000 'API'; Stop-PortPid 5173 'Vite' }
    'restart' { Stop-PortPid 8000 'API'; Start-Sleep -Seconds 2; Start-Api; Show-Status }
    'status'  { Show-Status }
}
