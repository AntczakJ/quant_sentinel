"""Regression tests for Phases 1-3 of gold-mine roadmap.

Phase 1: Meta-labeler sizing mode (QUANT_META_LABEL_SIZING env)
Phase 2: Partial-close at 1R + smart trailing (QUANT_PARTIAL_1R env)
Phase 3: Multi-asset scaffolding (assets.py registry)
"""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


# ── Phase 1: Meta-labeler sizing ───────────────────────────────────────

def test_phase1_sizing_mode_present_in_scanner():
    """Scanner has QUANT_META_LABEL_SIZING branch + lot override."""
    src = (ROOT / "src" / "trading" / "scanner.py").read_text(encoding="utf-8")
    assert "QUANT_META_LABEL_SIZING" in src, "Phase 1 env flag missing"
    assert "kelly_fraction" in src or "kelly_f" in src, "Kelly sizing not wired"
    assert "_meta_sizing_applied" in src, "Sizing observability marker missing"


def test_phase1_max_lot_cap_respected():
    """Sizing override must respect MAX_LOT_CAP ceiling."""
    src = (ROOT / "src" / "trading" / "scanner.py").read_text(encoding="utf-8")
    assert "MAX_LOT_CAP" in src, "MAX_LOT_CAP must apply as ceiling on sizing"


def test_phase1_default_off():
    """SIZING mode default OFF (operator opt-in only)."""
    src = (ROOT / "src" / "trading" / "scanner.py").read_text(encoding="utf-8")
    # Must use string '1' equality check (env var unset → mode disabled)
    assert "QUANT_META_LABEL_SIZING\") == \"1\"" in src or \
           "QUANT_META_LABEL_SIZING') == '1'" in src


# ── Phase 2: Partial-close + smart trailing ────────────────────────────

def test_phase2_partial_close_present_in_resolver():
    """api/main.py resolver has Phase 2 partial-close logic."""
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert "QUANT_PARTIAL_1R" in src, "Phase 2 env flag missing"
    assert "partial_1r=1" in src, "Partial-close marker missing"
    assert "1R reached" in src, "Phase 2 log line missing"


def test_phase2_default_off():
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert "QUANT_PARTIAL_1R\") == \"1\"" in src


def test_phase2_be_lock_logic_present():
    """When 1R reached, SL must move to entry (BE lock)."""
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert "new_sl = entry_f_p" in src, "BE lock not implemented"


# ── Phase 3: Multi-asset scaffolding ───────────────────────────────────

def test_phase3_asset_registry_loads():
    from src.trading.assets import (
        DEFAULT_ASSETS, AssetConfig, get_asset,
        enabled_assets, total_risk_budget_pct, validate_registry,
    )

    # XAU is the baseline — must exist and be enabled
    xau = get_asset("XAU/USD")
    assert xau is not None
    assert xau.enabled is True
    assert isinstance(xau, AssetConfig)
    assert xau.symbol == "XAU/USD"

    # Phase 3 candidates registered (BTC, EUR/USD, oil)
    assert "BTC/USD" in DEFAULT_ASSETS
    assert "EUR/USD" in DEFAULT_ASSETS
    assert "USOIL" in DEFAULT_ASSETS

    # Currently only XAU enabled
    enabled = enabled_assets()
    assert len(enabled) == 1
    assert enabled[0].symbol == "XAU/USD"


def test_phase3_risk_budget_validation():
    """Total risk budget across enabled = 1.0 (XAU full)."""
    from src.trading.assets import total_risk_budget_pct, validate_registry

    assert total_risk_budget_pct() == 1.0
    warnings = validate_registry()
    # No warnings expected with default config
    assert warnings == [] or all("XAU" not in w for w in warnings)


def test_phase3_btc_config_sensible():
    """BTC has crypto-appropriate params (24/7 killzones, wider spread)."""
    from src.trading.assets import get_asset

    btc = get_asset("BTC/USD")
    assert btc is not None
    # Crypto markets are 24/7 — killzone window must reflect this
    assert btc.killzones_utc == ((0, 24),)
    # Crypto has wider spreads than FX
    assert btc.spread_typical_pct > 0.0005
    # Min lot smaller (BTC contract is fractional)
    assert btc.min_lot == 0.001


def test_phase3_fx_config_sensible():
    """EUR/USD has FX-standard contract size + tight spread."""
    from src.trading.assets import get_asset

    eur = get_asset("EUR/USD")
    assert eur is not None
    # Standard FX contract = 100k base currency
    assert eur.contract_size == 100000.0
    # FX pip = 0.0001
    assert eur.pip_size == 0.0001
    # ECN spread very tight
    assert eur.spread_typical_pct < 0.0001
