"""
src/core/queries/ — domain-split SQL helpers.

2026-05-04: scaffold for breaking up the god module `src/core/database.py`
(113 inbound imports, 89 methods) per architecture audit. NewsDB stays
as the facade (no breaking change), but new code can import direct
domain helpers from here.

Migration path:
1. Extract most-used queries into domain modules (this directory)
2. NewsDB methods can call the domain helpers internally
3. New code prefers `from src.core.queries.trades import get_recent_trades`
4. Eventually deprecate NewsDB methods that have a queries/ equivalent.

Modules:
- trades.py — get/list/aggregate trades
- params.py — dynamic_params read/write/mirror
- sessions.py — session classification + WR
- rejections.py — rejected_setups queries

Each module gets its own connection from `src.core.database._conn`.
"""
