"""
src/db_backup.py — SQLite Database Backup Automation

Features:
  - On-demand backup (before risky operations)
  - Scheduled daily backup
  - Rotation (keep last N backups)
  - WAL mode for better concurrent access
  - Backup integrity verification

Usage:
  from src.ops.db_backup import create_backup, enable_wal_mode
  backup_path = create_backup()          # creates timestamped backup
  enable_wal_mode()                       # enable WAL for performance
"""

import os
import shutil
import sqlite3
import datetime
from pathlib import Path
from src.core.logger import logger

# Configuration
BACKUP_DIR = "data/backups"
MAX_BACKUPS = 7  # Keep last 7 backups
DB_PATH = os.getenv("DATABASE_URL", "data/sentinel.db")


def create_backup(reason: str = "manual") -> str:
    """
    Create a timestamped backup of the SQLite database.

    Args:
        reason: Why backup is being created (for log clarity)

    Returns:
        Path to the backup file, or empty string on failure.
    """
    if DB_PATH.startswith("libsql://"):
        logger.debug("Backup skipped — using Turso cloud database")
        return ""

    if not os.path.exists(DB_PATH):
        logger.warning(f"Database file not found: {DB_PATH}")
        return ""

    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"sentinel_{ts}_{reason}.db"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        # Use SQLite online backup API (safe even during writes)
        source = sqlite3.connect(DB_PATH)
        dest = sqlite3.connect(backup_path)
        source.backup(dest)
        dest.close()
        source.close()

        # Verify backup
        size_kb = os.path.getsize(backup_path) / 1024
        verify = sqlite3.connect(backup_path)
        verify.execute("SELECT COUNT(*) FROM trades")
        verify.close()

        logger.info(f"[BACKUP] Created: {backup_path} ({size_kb:.0f} KB, reason: {reason})")

        # Rotate old backups
        _rotate_backups()

        return backup_path

    except Exception as e:
        logger.error(f"[BACKUP] Failed: {e}")
        return ""


def _rotate_backups():
    """Remove oldest backups, keeping only MAX_BACKUPS most recent."""
    try:
        if not os.path.exists(BACKUP_DIR):
            return

        backups = sorted(
            Path(BACKUP_DIR).glob("sentinel_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
            logger.debug(f"[BACKUP] Rotated: {old_backup.name}")

    except Exception as e:
        logger.debug(f"[BACKUP] Rotation error: {e}")


def enable_wal_mode():
    """
    Enable WAL (Write-Ahead Logging) mode for better concurrent access.

    Benefits:
      - Readers don't block writers (and vice versa)
      - Better performance for mixed read/write workloads
      - Crash recovery via WAL journal

    NOTE: Skipped in Docker containers — WAL doesn't work reliably
    with Docker bind mounts on Windows (known SQLite limitation).
    """
    if DB_PATH.startswith("libsql://"):
        return

    # Skip WAL in Docker (bind mount compatibility issue)
    import os
    if os.path.exists("/.dockerenv"):
        logger.info("[DB] Docker detected — using default journal mode (not WAL)")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.close()
        logger.info(f"[DB] Journal mode: {mode[0]}")
    except Exception as e:
        logger.debug(f"WAL mode setup: {e}")


def get_backup_list() -> list:
    """List all existing backups with metadata."""
    if not os.path.exists(BACKUP_DIR):
        return []

    backups = []
    for f in sorted(Path(BACKUP_DIR).glob("sentinel_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        backups.append({
            "filename": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "created": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups
