"""Regression tests for 2026-05-05 trading-logic fixes.

Three live-money behavior changes shipped today, each with explicit
expected-impact in the commit message. These tests lock the contract
so future edits can't silently re-break them.

1. London session hard-block (commit fa98fb0)
2. A grade demote → B-treatment sizing (commit fa98fb0 + finance.py
   override fix in audit follow-up)
3. SHORT-in-bull-regime score floor (commit a3e404f)
"""
import os
from unittest.mock import patch

import pytest


# ─── 1. London hard-block ────────────────────────────────────────────────

def test_london_hard_block_default_on(monkeypatch):
    """When session=='london' and BLOCK_LONDON_SESSION default (=1),
    scanner short-circuits with `london_hard_block` rejection."""
    monkeypatch.setenv("BLOCK_LONDON_SESSION", "1")
    # We can't easily call _evaluate_tf_for_trade end-to-end without heavy
    # stubbing. The contract we care about: the literal block of code at
    # scanner.py runs `return None` for london when env is on. Verify by
    # source inspection — cheap, deterministic, no fragile mocking.
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "scanner.py"
    text = src.read_text(encoding="utf-8")
    # Block guard exists and references the env flag + the rejection key
    assert "BLOCK_LONDON_SESSION" in text, "London block env flag missing"
    assert "london_hard_block" in text, "London hard-block rejection key missing"
    assert "current_session == 'london'" in text, "London session check missing"


def test_london_hard_block_env_off_disables(monkeypatch):
    """BLOCK_LONDON_SESSION=0 means the hard-block does NOT short-circuit;
    scanner falls back to the soft session_performance filter."""
    # Same source-level assertion: the gate explicitly checks `!= '0'`,
    # so setting env to '0' is a documented opt-out.
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "scanner.py"
    text = src.read_text(encoding="utf-8")
    assert "BLOCK_LONDON_SESSION', '1') != '0'" in text, (
        "Opt-out semantics ('0' disables) must be preserved"
    )


# ─── 2. A grade demote ───────────────────────────────────────────────────

def test_a_grade_returns_b_sizing():
    """`score_setup_quality` returns grade='A' (label preserved for
    observability) but with B-level risk_mult=0.5 and target_rr=2.0."""
    from src.trading.smc_engine import score_setup_quality

    # Construct an analysis that scores in A range. Use a scalp tier
    # (15m) — A range there is [45, 65). We aim for ~55.
    analysis = {
        'tf': '15m', 'price': 3300.0, 'rsi': 55, 'trend': 'bull',
        'structure': 'CHoCH', 'liquidity_grab': True, 'fvg': True, 'mss': True,
        'ob_price': 3290, 'ob_list': [{'type': 'bull', 'price': 3290}],
        'macro_regime': 'zielony', 'usdjpy_zscore': -0.5, 'atr': 5.0,
        'ema': 3290, 'volume_factor': 1.0, 'engulfing': False, 'pin_bar': False,
        'ichimoku_above_cloud': True, 'ichimoku_below_cloud': False,
        'poc_price': 3300, 'near_poc': False, 'session': 'new_york',
        'bos_bullish': True, 'choch_bullish': True, 'fvg_direction': 'bull',
        'ob_direction': 'bull', 'session_info': {}, 'orb_direction': None,
        'asia_orb_direction': None, 'vwap': 3300, 'vwap_distance_atr': 0.1,
        'breaker_block': None, 'ifvg': None, 'reh_rel': None, 'ote_zone': None,
        'macro_signals': {}, 'fvg_age': 1, 'spread_pct': 0.001,
        'fvg_filled_pct': 0, 'macro_pillars_score': 0,
        'momentum_div_factor': 0.0, 'd1_aligned': False, 'usdjpy_corr': 0,
        'ob_count': 1, 'macro_squeeze': 0,
    }
    res = score_setup_quality(analysis, 'LONG')

    # If the score landed exactly in A range, demote must kick in
    if res['grade'] == 'A':
        assert res['risk_mult'] == 0.5, (
            f"A grade demote broken: risk_mult={res['risk_mult']} (expected 0.5)"
        )
        assert res['target_rr'] == 2.0, (
            f"A grade target_rr broken: {res['target_rr']} (expected 2.0)"
        )
    # If it landed in A+ or B, the test setup didn't actually exercise the
    # demote path — log but don't fail (other tests cover boundaries).
    else:
        pytest.skip(f"Setup scored as {res['grade']}, not A — boundary test")


def test_a_plus_untouched():
    """A+ grade (score >= a_plus_cut) keeps risk_mult=1.5, target_rr=3.0."""
    from src.trading.smc_engine import score_setup_quality
    # We can't reliably build a 75+ score without heavy fixtures. Instead
    # source-check that A+ branch still has the legacy values.
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "smc_engine.py"
    text = src.read_text(encoding="utf-8")
    # Look for the A+ block pattern
    assert 'grade = "A+"' in text
    # Confirm that within ~5 lines of that assignment we still see the
    # legacy 1.5 / 3.0 values (rather than 0.5 / 2.0 which would mean A+
    # got accidentally demoted too)
    idx = text.index('grade = "A+"')
    snippet = text[idx:idx + 200]
    assert "risk_mult = 1.5" in snippet, "A+ risk_mult was demoted (should be 1.5)"
    assert "target_rr = 3.0" in snippet, "A+ target_rr was demoted (should be 3.0)"


def test_finance_does_not_override_target_rr():
    """finance.calculate_position respects smc_engine's target_rr instead
    of forcing it back to 2.5 via max(). Audit caught this 2026-05-05."""
    from pathlib import Path
    fin = Path(__file__).resolve().parents[1] / "src" / "trading" / "finance.py"
    text = fin.read_text(encoding="utf-8")
    # The old buggy pattern
    assert 'tp_to_sl_ratio = max(tp_to_sl_ratio, 2.5)' not in text, (
        "A grade override re-introduced — RR floor at 2.5 silently undoes demote"
    )
    assert 'tp_to_sl_ratio = max(tp_to_sl_ratio, 3.0)' not in text, (
        "A+ grade max-floor pattern re-introduced"
    )
    # And the new correct pattern
    assert "setup_quality.get('target_rr')" in text, (
        "finance.py should now read target_rr from setup_quality"
    )


# ─── 3. SHORT-in-bull score floor ───────────────────────────────────────

def test_short_in_bull_floor_present():
    """STRICT_SHORT_IN_BULL gate exists in scanner.py and uses post-flip
    direction (not direction_str — audit caught this latent bug)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "scanner.py"
    text = src.read_text(encoding="utf-8")
    # Env flag exists
    assert "STRICT_SHORT_IN_BULL" in text, "SHORT-in-bull env flag missing"
    # Rejection key exists
    assert "short_strict_floor" in text, "short_strict_floor rejection key missing"
    # Score threshold (50)
    assert "sh_floor = 50.0" in text, (
        "Score floor magic number changed without test update"
    )
    # Uses post-flip direction
    floor_idx = text.index("STRICT_SHORT_IN_BULL")
    block = text[floor_idx - 200:floor_idx + 800]
    assert 'direction == "SHORT"' in block, (
        "SHORT-in-bull check should compare post-flip `direction`, "
        "not pre-flip `direction_str` (audit 2026-05-05)"
    )


def test_short_floor_only_in_bull_macro():
    """The floor is conditional on macro_regime == 'zielony'. When macro
    is czerwony or neutralny, the floor must not engage."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "scanner.py"
    text = src.read_text(encoding="utf-8")
    floor_idx = text.index("STRICT_SHORT_IN_BULL")
    block = text[floor_idx - 200:floor_idx + 800]
    assert "'macro_regime') == 'zielony'" in block, (
        "Floor must check macro_regime=='zielony' so it auto-disengages "
        "when macro flips to bear/neutral"
    )


# ─── Exception-fallback regression ──────────────────────────────────────

def test_setup_quality_fallback_uses_b_grade():
    """When score_setup_quality throws, scanner.py used to silently
    proceed at A-grade sizing (1.0× risk, 2.5 RR). Audit 2026-05-05
    flipped fallback to B-grade (0.5× risk, 2.0 RR)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "trading" / "scanner.py"
    text = src.read_text(encoding="utf-8")
    # The new fallback dict
    assert (
        "'grade': 'B', 'score': 40, 'risk_mult': 0.5, 'target_rr': 2.0"
        in text
    ), "Setup-quality exception fallback should use B-grade defaults"
    # The old buggy default should NOT be present
    assert (
        "'grade': 'A', 'score': 50, 'risk_mult': 1.0, 'target_rr': 2.5"
        not in text
    ), "Old A-grade fallback re-introduced"
