#!/usr/bin/env bash
# scripts/offhost_backup_sync.sh — push local backups to off-host storage.
#
# 2026-05-05: shipped per comparative research adoption (off-host backup
# = #4 ranked task). Single-machine deployment is a single point of failure;
# disk crash / ransomware / windows update reboot all wipe state.
#
# Defaults to rclone with remote alias "qs_backup" (configure once with
# `rclone config`). Override remote with QS_BACKUP_REMOTE env var.
#
# Targets:
#   data/backups/                   — daily DB snapshots (sentinel.db.bak)
#   data/sentinel.db                — current production DB (live, hot-backup)
#   data/backtest.db                — last finished backtest DB
#   reports/                        — backtest result JSONs + walk-forward reports
#   memory/                         — Claude memory files (cross-session)
#   models/                         — trained model weights (heavy but irreplaceable)
#
# RTO target: 2 hours (download + restore drill from off-host).
# RPO target: 1 hour (with hourly backup cron + this nightly off-host sync).
#
# Usage:
#   bash scripts/offhost_backup_sync.sh             # full sync, default remote
#   QS_BACKUP_REMOTE=b2:my-bucket ./scripts/offhost_backup_sync.sh
#   DRY_RUN=1 ./scripts/offhost_backup_sync.sh      # preview only
#
# Schedule (Windows Task Scheduler):
#   Daily 03:00 local — runs after _daily_db_backup so newest snapshot is included.
#
# Schedule (cron on Linux/macOS):
#   0 3 * * * cd /path/to/quant_sentinel && bash scripts/offhost_backup_sync.sh

set -euo pipefail

cd "$(dirname "$0")/.."

REMOTE="${QS_BACKUP_REMOTE:-qs_backup:quant_sentinel}"
DRY_FLAG=""
if [ "${DRY_RUN:-0}" = "1" ]; then
    DRY_FLAG="--dry-run"
    echo "[backup] DRY-RUN — no actual upload"
fi

# Pre-flight: confirm rclone is installed + remote is configured
if ! command -v rclone >/dev/null 2>&1; then
    echo "ERROR: rclone not found. Install: https://rclone.org/install/" >&2
    exit 1
fi

if ! rclone listremotes | grep -q "^${REMOTE%%:*}:"; then
    echo "ERROR: rclone remote '${REMOTE%%:*}' not configured." >&2
    echo "Run: rclone config" >&2
    echo "  Recommended: Backblaze B2 (5 GB free) or Wasabi" >&2
    exit 1
fi

ts=$(date +%Y%m%d_%H%M%S)
echo "[backup] $ts — syncing to ${REMOTE}"

# Sync each path with retention. --transfers=2 keeps local IO low.
# --max-age 90d on backup folder = older than 90d cleaned remotely.
sync_path() {
    local src="$1"
    local dst_subdir="$2"
    local extra_args="${3:-}"
    if [ ! -e "$src" ]; then
        echo "[backup] skip ${src} (does not exist)"
        return 0
    fi
    echo "[backup] $src → ${REMOTE}/${dst_subdir}"
    rclone sync "$src" "${REMOTE}/${dst_subdir}" \
        --transfers=2 \
        --bwlimit 4M \
        --log-level INFO \
        $DRY_FLAG \
        $extra_args \
        2>&1 | tail -5
}

# Daily DB snapshots — keep 90d remote
sync_path "data/backups" "data/backups" "--max-age 90d"

# Live production DB (single file, fast)
sync_path "data/sentinel.db" "data/sentinel.db.latest"

# Last finished backtest DB
sync_path "data/backtest.db" "data/backtest.db.latest"

# Backtest reports (small JSONs, keep all)
sync_path "reports" "reports"

# Memory files (cross-session continuity, very small)
sync_path "memory" "memory"

# Model weights (heavy but irreplaceable on retrain ~12min/voter)
# --bwlimit higher here; runs once a day so brief spike is fine
sync_path "models" "models" "--bwlimit 8M"

echo "[backup] $ts — sync complete. Remote: ${REMOTE}"

# Append timestamp to local audit log
mkdir -p logs
echo "$(date -Iseconds) sync OK to ${REMOTE}" >> logs/offhost_backup.log
