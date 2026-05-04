"""Regression tests for regime routing module."""
from src.analysis.regime_routing import (
    RegimeRouting, get_routing, is_active, explain_routing,
)


def test_squeeze_blocks_all_tfs():
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        r = get_routing("squeeze", tf)
        assert r.block_entry, f"squeeze should block {tf}"


def test_ranging_uses_higher_min_score():
    r_trend = get_routing("trending_high_vol", "5m")
    r_range = get_routing("ranging", "5m")
    assert r_range.min_score_floor > r_trend.min_score_floor, \
        "ranging must require higher score than trending"


def test_ranging_mutes_trend_voters():
    r = get_routing("ranging", "5m")
    assert r.voter_weight_mult.get("lstm", 1.0) < 1.0, "ranging should mute LSTM"
    assert r.voter_weight_mult.get("dqn", 1.0) < 1.0, "ranging should mute DQN"
    assert r.voter_weight_mult.get("smc", 1.0) > 1.0, "ranging should boost SMC"


def test_trending_high_vol_boosts_trend_voters():
    r = get_routing("trending_high_vol", "5m")
    assert r.voter_weight_mult.get("lstm", 1.0) > 1.0
    assert r.voter_weight_mult.get("dqn", 1.0) > 1.0


def test_macro_zielony_filters_to_long_only():
    r = get_routing("trending_high_vol", "15m", macro_regime="zielony")
    assert r.allowed_directions == ("LONG",), \
        f"zielony macro should restrict to LONG, got {r.allowed_directions}"


def test_macro_czerwony_filters_to_short_only():
    r = get_routing("trending_high_vol", "15m", macro_regime="czerwony")
    assert r.allowed_directions == ("SHORT",)


def test_macro_neutralny_keeps_both_directions():
    r = get_routing("trending_low_vol", "15m", macro_regime="neutralny")
    assert set(r.allowed_directions) == {"LONG", "SHORT"}


def test_squeeze_plus_macro_still_blocks():
    r = get_routing("squeeze", "5m", macro_regime="zielony")
    assert r.block_entry, "squeeze blocks regardless of macro"


def test_explain_routing_returns_dict():
    d = explain_routing("trending_high_vol", "1h", "zielony")
    assert d["market_regime"] == "trending_high_vol"
    assert d["tf"] == "1h"
    assert d["macro_regime"] == "zielony"
    assert "min_score_floor" in d
    assert "voter_weight_mult" in d


def test_default_inactive(monkeypatch):
    monkeypatch.delenv("QUANT_REGIME_V2", raising=False)
    assert is_active() is False


def test_active_when_env_set(monkeypatch):
    monkeypatch.setenv("QUANT_REGIME_V2", "1")
    assert is_active() is True


def test_unknown_regime_returns_default():
    """Defensive — any classifier output we don't expect should not crash."""
    r = get_routing("unknown_regime", "5m")  # type: ignore[arg-type]
    assert r.block_entry is False
    assert r.min_score_floor is None
    assert r.allowed_directions == ("LONG", "SHORT")
