$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path (Split-Path -Parent $ScriptDir)

if ($env:QS_BACKUP_REMOTE) {
    $Remote = $env:QS_BACKUP_REMOTE
} else {
    # Default bucket — override via $env:QS_BACKUP_REMOTE if your bucket
    # has a different name. Bucket must match the application-key scope
    # set in Backblaze B2 dashboard (Application Keys → Allow access to).
    $Remote = "qs_backup:qs-backup-1234"
}

$DryRun = ($env:DRY_RUN -eq "1")
if ($DryRun) {
    Write-Host "[backup] DRY-RUN mode - no actual upload" -ForegroundColor Yellow
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    Write-Error "rclone not found. Install: https://rclone.org/install/"
    exit 1
}

$RemoteName = ($Remote -split ":")[0]
$Remotes = & rclone listremotes
$RemoteFound = $false
foreach ($r in $Remotes) {
    if ($r.TrimEnd(":") -eq $RemoteName) {
        $RemoteFound = $true
        break
    }
}
if (-not $RemoteFound) {
    Write-Error "rclone remote '$RemoteName' not configured. Run: rclone config"
    Write-Host "Recommended: Backblaze B2 - 5GB free tier" -ForegroundColor Yellow
    exit 1
}

$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
Write-Host "[backup] $Ts - syncing to $Remote" -ForegroundColor Cyan

function Sync-Item-Path {
    param(
        [string]$Src,
        [string]$DstSubdir,
        [string[]]$ExtraArgs = @()
    )

    if (-not (Test-Path $Src)) {
        Write-Host "[backup] skip $Src - does not exist" -ForegroundColor DarkGray
        return
    }

    $Dst = "$Remote/$DstSubdir"
    Write-Host "[backup] $Src -> $Dst"

    $rcArgs = @("sync", $Src, $Dst, "--transfers=2", "--bwlimit", "4M", "--log-level", "INFO")
    if ($DryRun) {
        $rcArgs += "--dry-run"
    }
    $rcArgs += $ExtraArgs

    & rclone @rcArgs
}

Sync-Item-Path -Src "data/backups" -DstSubdir "data/backups" -ExtraArgs @("--max-age", "90d")
Sync-Item-Path -Src "data/sentinel.db" -DstSubdir "data/sentinel.db.latest"
Sync-Item-Path -Src "data/backtest.db" -DstSubdir "data/backtest.db.latest"
Sync-Item-Path -Src "reports" -DstSubdir "reports"
Sync-Item-Path -Src "memory" -DstSubdir "memory"
Sync-Item-Path -Src "models" -DstSubdir "models" -ExtraArgs @("--bwlimit", "8M")

Write-Host "[backup] $Ts - sync complete. Remote: $Remote" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$LogTs = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
$LogLine = "$LogTs sync OK to $Remote"
Add-Content -Path "logs/offhost_backup.log" -Value $LogLine
