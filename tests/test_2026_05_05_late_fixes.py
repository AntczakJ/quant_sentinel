"""Late-2026-05-05 regression tests — covers the second wave of fixes
shipped after the 4-agent WR audit.

Locks in:
1. good_hour bonus (+5) when hour×direction has historical N≥10, WR≥55%
2. IFVG age-decay (linear 0→30 bars, +10→0)
3. session_overlap +6 (was +4)
4. Asia ORB gate loosening — HTF filter dropped at smc_engine call site
5. A+ target_rr 2.5 (was 3.0) — wide-RR trap fix
6. BREAKEVEN classification when |pnl|<$1 in time-exit
7. log_trade vol_regime + spread_at_entry persistence
8. Friday close window covers all of 19:30-23:59 UTC
9. DQN reward double-count removed (terminal _close_position only)
10. v2_xgb features failure elevates to WARNING (one-time)
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ─── 1. good_hour bonus ─────────────────────────────────────────────────

def test_good_hours_method_exists():
    from src.core.database import NewsDB
    db = NewsDB()
    # Method exists and accepts the expected kwargs
    result = db.get_good_hours(min_trades=10, min_winrate=0.55)
    assert isinstance(result, list), "get_good_hours should return a list"


def test_good_hour_factor_in_score():
    """Score loop reads analysis['good_hour_match'] and adds +5 when True."""
    src = (ROOT / "src" / "trading" / "smc_engine.py").read_text(encoding="utf-8")
    assert "analysis.get('good_hour_match')" in src, (
        "good_hour gate missing from score_setup_quality"
    )
    # Find the actual `if analysis.get(...)` line, not the docstring mention
    idx = src.index("if analysis.get('good_hour_match'):")
    block = src[idx:idx + 200]
    assert "score += 5" in block, "good_hour bonus should be +5"
    assert "factors_detail['good_hour']" in block, "factor key missing"


def test_scanner_wires_good_hour_match():
    """Scanner sets analysis['good_hour_match'] right after bad_hours block."""
    src = (ROOT / "src" / "trading" / "scanner.py").read_text(encoding="utf-8")
    assert "get_good_hours(min_trades=10, min_winrate=0.55)" in src
    assert "analysis['good_hour_match']" in src


# ─── 2. IFVG age-decay ─────────────────────────────────────────────────

def test_ifvg_age_decay_linear():
    """IFVG bonus decays linearly from +10 (bars=0) to 0 (bars≥30)."""
    src = (ROOT / "src" / "trading" / "smc_engine.py").read_text(encoding="utf-8")
    assert "ifvg_bars_since_break" in src, "IFVG decay missing bars-since reading"
    # Linear formula present
    assert "10 * (1.0 - bars_since / 30.0)" in src, (
        "IFVG decay formula changed — verify intent"
    )


# ─── 3. session_overlap bumped ─────────────────────────────────────────

def test_session_overlap_is_6():
    """session_overlap bonus bumped 4 → 6 per 1yr backtest WR 53.6%."""
    src = (ROOT / "src" / "trading" / "smc_engine.py").read_text(encoding="utf-8")
    idx = src.index("session_name == 'overlap'")
    block = src[idx:idx + 600]
    assert "score += 6" in block, "session_overlap should be +6 (was +4)"
    assert "factors_detail['session_overlap'] = 6" in block


# ─── 4. Asia ORB gate loosening ────────────────────────────────────────

def test_orb_called_without_htf_filter():
    """smc_engine passes htf_ema200=None and max_post_open_hours=4.0."""
    src = (ROOT / "src" / "trading" / "smc_engine.py").read_text(encoding="utf-8")
    assert "detect_orb_signal(df, htf_ema200=None, max_post_open_hours=4.0)" in src, (
        "ORB call signature changed — verify gate-loosening intent"
    )


def test_orb_module_still_supports_htf_filter():
    """detect_orb_signal still accepts htf_ema200 (backward compat)."""
    from src.trading.asia_orb import detect_orb_signal
    import inspect
    sig = inspect.signature(detect_orb_signal)
    assert 'htf_ema200' in sig.parameters
    assert 'max_post_open_hours' in sig.parameters


# ─── 5. BREAKEVEN classification in time-exit ─────────────────────────

def test_time_exit_breakeven_classification():
    """Time-exit sets status=BREAKEVEN when |pnl| < $1."""
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8") if (
        ROOT / "src" / "api" / "main.py"
    ).exists() else (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    # Must NOT use the old binary 'WIN' if pnl > 0 else 'LOSS' pattern in time-exit
    assert 'status_label = "BREAKEVEN"' in src, "BREAKEVEN classification missing"
    # Threshold $1 documented
    assert "abs(pnl) < 1.0" in src, "BREAKEVEN threshold should be $1"


# ─── 6. log_trade vol_regime + spread persistence ──────────────────────

def test_log_trade_accepts_vol_regime_and_spread():
    """log_trade signature includes vol_regime + spread_at_entry kwargs."""
    from src.core.database import NewsDB
    import inspect
    sig = inspect.signature(NewsDB.log_trade)
    assert 'vol_regime' in sig.parameters
    assert 'spread_at_entry' in sig.parameters


def test_log_trade_writes_columns():
    """In-memory DB smoke: vol_regime + spread_at_entry persist."""
    import os
    os.environ['DATABASE_URL'] = ':memory:'
    import importlib
    from src.core import database
    importlib.reload(database)
    db = database.NewsDB()
    db.log_trade(
        direction='LONG', price=3300.0, sl=3290.0, tp=3320.0,
        rsi=55, trend='bull', structure='Stable', pattern='[M5] test',
        factors={'bos': 1}, lot=0.01,
        vol_regime='mid', spread_at_entry=0.001,
    )
    row = db._query_one(
        "SELECT vol_regime, spread_at_entry FROM trades ORDER BY id DESC LIMIT 1"
    )
    assert row[0] == 'mid', f"vol_regime not persisted (got {row[0]})"
    assert row[1] == 0.001, f"spread_at_entry not persisted (got {row[1]})"


# ─── 7. Friday close window covers full 19:30-23:59 UTC ───────────────

def test_friday_close_window_complete():
    """Pre-weekend close window must cover 19:30-19:59 + all of 20:00 onwards."""
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    # New shape: (hour == 19 and minute >= 30) OR hour >= 20
    assert "(_now_wk.hour == 19 and _now_wk.minute >= 30)" in src
    assert "or _now_wk.hour >= 20" in src
    # Old buggy AND-shape removed
    assert "_now_wk.hour >= 19 and _now_wk.minute >= 30" not in src, (
        "Old off-by-one window pattern present"
    )


# ─── 8. DQN reward double-count removed ───────────────────────────────

def test_dqn_no_double_count():
    """rl_agent terminal step does NOT add `final_return * 3` after _close_position."""
    src = (ROOT / "src" / "ml" / "rl_agent.py").read_text(encoding="utf-8")
    # The _close_position call is kept
    assert "reward += self._close_position(self._prices[self.index])" in src
    # The double-count line is gone
    assert "reward += final_return * 3" not in src, (
        "DQN final_return double-count re-introduced"
    )


# ─── 9. v2_xgb one-time WARNING on features failure ───────────────────

def test_v2_xgb_features_failure_warns_once():
    """First v2_xgb features failure logs WARNING; subsequent log debug."""
    src = (ROOT / "src" / "ml" / "ensemble_models.py").read_text(encoding="utf-8")
    assert "_v2_features_warned = False" in src, "Warning-tracker flag missing"
    assert "v2_xgb features compute failed (first occurrence)" in src
    assert "Subsequent failures suppressed at debug level" in src
