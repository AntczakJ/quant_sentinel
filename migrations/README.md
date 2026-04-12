# Database migrations

Lightweight migration framework — see `src/core/migrations.py`.

## File format

`migrations/NNNN_description.py` (4-digit zero-padded, sorted alphabetically).

```python
# migrations/0042_add_foo_column.py

def up(conn):
    """Apply this migration."""
    conn.execute("ALTER TABLE trades ADD COLUMN foo TEXT")
    # Any additional data backfill here


def down(conn):
    """Optional: revert this migration."""
    # SQLite doesn't support DROP COLUMN directly; would need table rebuild
    raise NotImplementedError("Manual rollback required for trades.foo")
```

## Apply migrations

```bash
# Automatic (on API startup — add to api/main.py lifespan)
python -m src.core.migrations

# Rollback to specific version
python -m src.core.migrations rollback 0041
```

## Integration with existing schema

Current schema (CHANGELOG v3.0.0 baseline) lives in `src/core/database.py`
`create_tables()` + `migrate()`. New changes should live in migrations/
going forward. A `0001_baseline.py` can optionally snapshot current schema
but existing databases already have tables, so it would be a no-op.

## When to write a migration vs edit database.py

| Change | Where |
|---|---|
| New table | `migrations/NNNN_...py` (easier to track + rollback) |
| New column on existing table | `migrations/NNNN_...py` |
| New index | `migrations/NNNN_...py` |
| Fix bug in existing schema | migration, not database.py |
| Initial bootstrap | `database.py::create_tables()` (already there) |

## Safety

- Each migration runs in a transaction — failure rolls back completely.
- Applied migrations recorded in `schema_migrations` table.
- Idempotent: running `run_migrations()` multiple times is safe.
- Migrations applied in filename sort order (NNNN_ prefix mandatory).

## Not alembic because

- Alembic requires SQLAlchemy ORM models (we use raw SQL).
- Overkill for single-file SQLite DB.
- This framework is ~200 LOC, no new deps, covers our needs.

If you need more (branched migrations, auto-generation from ORM diffs,
complex data transformations), install alembic properly and migrate
this system to SQLAlchemy Core.
