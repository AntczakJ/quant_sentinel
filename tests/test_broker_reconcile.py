"""Tests for scripts/broker_reconcile.py — DB↔broker fill reconciliation.

Verifies the 4 mismatch kinds: db_no_broker, broker_no_db, lot_mismatch,
slippage. Plus the happy path.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import broker_reconcile as br


def _db_row(trade_id, ts, direction, entry, lot):
    return {"id": trade_id, "ts": ts, "direction": direction, "entry": entry, "lot": lot}


def _broker_row(open_time, symbol, side, lot, open_price):
    return {
        "open_time": open_time, "symbol": symbol, "side": side,
        "lot": lot, "open_price": open_price,
        "close_time": "", "close_price": 0.0, "profit": 0.0,
    }


ALIASES = {"XAUUSD", "GOLD", "XAU/USD"}


def test_happy_path_no_mismatches():
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    broker = [_broker_row("2026-05-05 14:30:15", "XAUUSD", "buy", 0.01, 3300.10)]
    out = br.reconcile(broker, db, ALIASES)
    assert len(out) == 0, f"Expected zero mismatches, got {out}"


def test_db_no_broker():
    """DB trade with no broker counterpart."""
    db = [_db_row(99, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    out = br.reconcile([], db, ALIASES)
    assert len(out) == 1
    assert out[0]["kind"] == "db_no_broker"
    assert out[0]["trade_id"] == 99


def test_broker_no_db():
    """Broker fill with no DB counterpart (manual override)."""
    broker = [_broker_row("2026-05-05 14:30:00", "XAUUSD", "buy", 0.01, 3300.0)]
    out = br.reconcile(broker, [], ALIASES)
    assert len(out) == 1
    assert out[0]["kind"] == "broker_no_db"
    assert out[0]["trade_id"] is None


def test_lot_mismatch():
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    broker = [_broker_row("2026-05-05 14:30:00", "XAUUSD", "buy", 0.05, 3300.0)]
    out = br.reconcile(broker, db, ALIASES)
    kinds = [m["kind"] for m in out]
    assert "lot_mismatch" in kinds
    lm = next(m for m in out if m["kind"] == "lot_mismatch")
    assert lm["db_lot"] == 0.01
    assert lm["broker_lot"] == 0.05


def test_slippage_flagged_when_over_threshold():
    """0.5% slippage > 0.2% threshold should flag."""
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    # 3316.50 vs 3300 = 0.5% slippage
    broker = [_broker_row("2026-05-05 14:30:00", "XAUUSD", "buy", 0.01, 3316.50)]
    out = br.reconcile(broker, db, ALIASES)
    kinds = [m["kind"] for m in out]
    assert "slippage" in kinds


def test_slippage_clean_under_threshold():
    """0.05% slippage < 0.2% should NOT flag."""
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    # 3301.65 vs 3300 = 0.05% slippage
    broker = [_broker_row("2026-05-05 14:30:00", "XAUUSD", "buy", 0.01, 3301.65)]
    out = br.reconcile(broker, db, ALIASES)
    kinds = [m["kind"] for m in out]
    assert "slippage" not in kinds


def test_direction_disagreement_treated_as_orphan():
    """DB LONG vs broker SELL — they don't match, both flagged."""
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    broker = [_broker_row("2026-05-05 14:30:00", "XAUUSD", "sell", 0.01, 3300.0)]
    out = br.reconcile(broker, db, ALIASES)
    kinds = [m["kind"] for m in out]
    assert "db_no_broker" in kinds
    assert "broker_no_db" in kinds


def test_time_outside_window_treated_as_orphan():
    """Match window is ±60s; 5min apart → no match."""
    db = [_db_row(1, "2026-05-05 14:30:00", "LONG", 3300.0, 0.01)]
    broker = [_broker_row("2026-05-05 14:35:00", "XAUUSD", "buy", 0.01, 3300.0)]
    out = br.reconcile(broker, db, ALIASES)
    kinds = [m["kind"] for m in out]
    assert "db_no_broker" in kinds
    assert "broker_no_db" in kinds


def test_recon_table_created():
    """Smoke test the schema bootstrap."""
    conn = sqlite3.connect(":memory:")
    br._ensure_recon_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reconciliation)")}
    assert "trade_id" in cols
    assert "mismatch_kind" in cols
    assert "slippage_pct" in cols
    conn.close()
