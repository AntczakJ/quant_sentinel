# Schema Changes — How-To

Quant Sentinel uses SQLite with an idempotent migration pattern —
NOT alembic (overkill for single-file DB, single-process writer).

## Pattern

All schema lives in `src/core/database.py`:

1. **`NewsDB.create_tables()`** — CREATE TABLE IF NOT EXISTS for initial schema.
2. **`NewsDB.migrate()`** — idempotent ALTER TABLE ADD COLUMN IF NOT EXISTS
   for evolving existing tables.
3. Index creation in migrate() with CREATE INDEX IF NOT EXISTS.

Both are called on every NewsDB() instantiation (once per process via
`_db_initialized` flag).

## Adding a new table

```python
# src/core/database.py, in create_tables():
self._execute("""CREATE TABLE IF NOT EXISTS my_new_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    foo TEXT NOT NULL,
    bar REAL
)""")

# Also add index(es) in migrate():
self._execute("CREATE INDEX IF NOT EXISTS idx_my_table_foo ON my_new_table(foo)")
```

## Adding a column to existing table

```python
# src/core/database.py, in migrate():
try:
    cols = [r[1] for r in self._query("PRAGMA table_info(trades)")]
    if "new_column" not in cols:
        self._execute("ALTER TABLE trades ADD COLUMN new_column TEXT")
        logger.info("Migration: added trades.new_column")
except Exception as e:
    logger.warning(f"Migration failed: {e}")
```

SQLite ALTER TABLE ADD COLUMN is idempotent **only via the above existence
check** — SQLite itself will throw "duplicate column name" otherwise.

## Data backfill

For non-trivial migrations (e.g. computed values on existing rows):

```python
# Idempotent: only backfill rows with NULL in new column
self._execute("""
    UPDATE trades
    SET new_column = (entry - sl) * lot
    WHERE new_column IS NULL
""")
```

## Testing migrations

1. Copy `data/sentinel.db` to `/tmp/test.db`.
2. Delete schema you want to test migration for:
   ```bash
   sqlite3 /tmp/test.db "ALTER TABLE trades DROP COLUMN new_column"
   ```
3. Set `DATABASE_URL=/tmp/test.db` and import NewsDB — migration should run.
4. Verify: `sqlite3 /tmp/test.db "PRAGMA table_info(trades)"`

## When to consider alembic

Move to full alembic if you hit any of:
- Need to rollback migrations (current: forward-only)
- Schema changes require complex data transformations (beyond simple backfill)
- Multiple processes writing to DB concurrently (Turso already handles this
  via libsql — backtest and prod use separate files so it's fine)
- Team >3 developers making schema changes

Current scale (single VPS, single writer) doesn't justify overhead.

## Schema history

Major schema changes are tracked in CHANGELOG.md under "Changed" / "Added"
sections. DB file itself has no version table — schema is "whatever
create_tables() + migrate() produces on a fresh run".

For a structured audit: `sqlite3 data/sentinel.db ".schema"`
