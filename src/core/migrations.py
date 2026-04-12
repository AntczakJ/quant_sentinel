"""
src/core/migrations.py — Lightweight SQLite migration framework.

Alternative to alembic for projects using raw SQL (no SQLAlchemy ORM).
Each migration is a .py file in migrations/ with up() and optional down().

Schema version tracked in `schema_migrations` table (created on first run).

Usage in production:
    from src.core.migrations import run_migrations
    run_migrations()  # applies any pending

Adding a new migration:
    1. Create migrations/0042_add_foo_column.py with up(conn): ...
    2. Next startup applies it automatically.
    3. Recorded in schema_migrations table with applied_at timestamp.

Rollback:
    python -m src.core.migrations rollback 0041  # rolls back to 41

Safety:
- Each migration runs in a transaction (auto-rollback on failure).
- Migrations are applied in filename order (0001_, 0002_, ...).
- Applied migrations are skipped automatically (idempotent).
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from src.core.logger import logger


MIGRATIONS_DIR = Path("migrations")


def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Create the tracking table if not present."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def _list_migration_files() -> list[Path]:
    """Return sorted list of migration files (NNNN_description.py format)."""
    if not MIGRATIONS_DIR.exists():
        return []
    files = []
    for p in MIGRATIONS_DIR.glob("[0-9]*.py"):
        # Expected: 0001_init.py, 0002_add_foo.py, etc.
        files.append(p)
    return sorted(files, key=lambda p: p.name)


def _load_migration(path: Path) -> tuple[str, Callable, Optional[Callable]]:
    """Dynamically import migration module. Returns (version, up_fn, down_fn)."""
    version = path.stem.split("_", 1)[0]
    spec = importlib.util.spec_from_file_location(f"migration_{version}", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load migration {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "up"):
        raise RuntimeError(f"Migration {path} missing up() function")
    return version, module.up, getattr(module, "down", None)


def run_migrations(db_path: Optional[str] = None) -> list[str]:
    """Apply all pending migrations. Returns list of versions applied."""
    db_path = db_path or os.environ.get("DATABASE_URL", "data/sentinel.db")
    applied: list[str] = []

    conn = _connect(db_path)
    try:
        _ensure_migrations_table(conn)
        already = _applied_versions(conn)

        for path in _list_migration_files():
            version, up_fn, _down_fn = _load_migration(path)
            if version in already:
                continue
            logger.info(f"[migration] Applying {version}: {path.stem}")
            try:
                up_fn(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                    (version, path.stem)
                )
                conn.commit()
                applied.append(version)
                logger.info(f"[migration] {version} applied successfully")
            except Exception as e:
                conn.rollback()
                logger.error(f"[migration] {version} FAILED: {e}")
                raise RuntimeError(f"Migration {version} failed: {e}") from e
    finally:
        conn.close()

    if applied:
        logger.info(f"[migration] Applied {len(applied)} migrations: {applied}")
    return applied


def rollback(target_version: str, db_path: Optional[str] = None) -> list[str]:
    """Roll back migrations above target_version. Returns rolled-back versions."""
    db_path = db_path or os.environ.get("DATABASE_URL", "data/sentinel.db")
    rolled: list[str] = []

    conn = _connect(db_path)
    try:
        _ensure_migrations_table(conn)
        applied = sorted(_applied_versions(conn), reverse=True)

        for version in applied:
            if version <= target_version:
                break
            matching = [p for p in _list_migration_files() if p.stem.startswith(version)]
            if not matching:
                logger.warning(f"[migration] No file for applied version {version} — skipping rollback")
                continue
            _v, _up, down_fn = _load_migration(matching[0])
            if down_fn is None:
                raise RuntimeError(f"Migration {version} has no down() — manual rollback required")
            logger.info(f"[migration] Rolling back {version}")
            try:
                down_fn(conn)
                conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
                conn.commit()
                rolled.append(version)
            except Exception as e:
                conn.rollback()
                raise RuntimeError(f"Rollback of {version} failed: {e}") from e
    finally:
        conn.close()

    return rolled


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "rollback":
        target = sys.argv[2] if len(sys.argv) >= 3 else "0000"
        print(f"Rolling back to {target}...")
        rolled = rollback(target)
        print(f"Rolled back: {rolled}")
    else:
        print("Running pending migrations...")
        applied = run_migrations()
        print(f"Applied: {applied}" if applied else "No pending migrations")
