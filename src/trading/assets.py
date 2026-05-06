"""src/trading/assets.py — multi-asset configuration registry.

2026-05-06 (Phase 3): scaffolding for multi-asset expansion. Currently
single-XAU; this module is the seam for adding BTC + EUR/USD + oil etc
without rewriting scanner.py / smc_engine.py.

Pattern:
  - Each asset has an `AssetConfig` dataclass
  - Scanner can iterate registered assets per cycle
  - Per-asset risk budget enforced via portfolio cap
  - Per-asset regime params (e.g. ATR multiplier, killzones)

Phase 3 Step 1 (this file): config registry only. Scanner integration
comes in next iteration after baseline (XAU) is solid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssetConfig:
    """Per-asset trading parameters."""
    symbol: str                          # broker symbol e.g. "XAU/USD" or "BTC/USD"
    label: str                           # display name e.g. "Gold" or "Bitcoin"
    enabled: bool = True
    contract_size: float = 100.0         # oz per lot for XAU; 1.0 for BTC; 100k for FX
    pip_size: float = 0.01               # USD per pip for XAU; 0.0001 for FX
    min_lot: float = 0.01
    max_lot: float = 1.0
    atr_pip_multiplier: float = 1.0      # asset-specific ATR scale factor
    cascade_tfs: tuple[str, ...] = ("5m", "15m", "30m", "1h", "4h")
    risk_budget_pct: float = 1.0         # share of total risk budget (1.0 = full)
    spread_typical_pct: float = 0.0003   # typical spread as fraction of price
    killzones_utc: tuple[tuple[int, int], ...] = (
        (8, 10),   # London open
        (13, 15),  # NY open + London-NY overlap
    )
    macro_relevance: tuple[str, ...] = ()  # which macro signals matter (per asset)
    notes: str = ""


# Default asset registry — extend as you onboard new instruments
DEFAULT_ASSETS: dict[str, AssetConfig] = {
    "XAU/USD": AssetConfig(
        symbol="XAU/USD",
        label="Gold",
        enabled=True,
        contract_size=100.0,
        pip_size=0.01,
        min_lot=0.01,
        max_lot=1.0,
        atr_pip_multiplier=1.0,
        risk_budget_pct=1.0,                # 100% currently — all-in on gold
        spread_typical_pct=0.0003,           # ~$1.5 on $5000 spot
        killzones_utc=((8, 10), (13, 15)),
        macro_relevance=("usdjpy", "real_yields", "vixy", "gpr", "uup"),
        notes="Primary instrument. SMC + macro pillars + ICT confluence.",
    ),
    # 2026-05-06 — Phase 3 candidates (DISABLED until baseline + retrain):
    "BTC/USD": AssetConfig(
        symbol="BTC/USD",
        label="Bitcoin",
        enabled=False,                       # opt-in via this flag
        contract_size=1.0,                   # BTC standard contract
        pip_size=0.01,
        min_lot=0.001,
        max_lot=0.5,
        atr_pip_multiplier=1.0,
        risk_budget_pct=0.25,                # 25% of total risk budget
        spread_typical_pct=0.0008,           # crypto wider spreads
        killzones_utc=((0, 24),),            # 24/7 market
        macro_relevance=("vixy", "real_yields", "dxy"),
        notes="Crypto — high vol, 24/7. Disable killzones. Requires regime-specific params.",
    ),
    "EUR/USD": AssetConfig(
        symbol="EUR/USD",
        label="EUR/USD",
        enabled=False,
        contract_size=100000.0,              # FX standard lot = 100k EUR
        pip_size=0.0001,
        min_lot=0.01,
        max_lot=2.0,
        atr_pip_multiplier=10000.0,          # FX uses pips not cents
        risk_budget_pct=0.30,
        spread_typical_pct=0.00005,          # ECN spread
        killzones_utc=((7, 9), (12, 14)),    # Frankfurt + NY
        macro_relevance=("ecb_rate", "fed_rate", "real_yields"),
        notes="Most liquid FX. Tight spreads. Macro-driven.",
    ),
    "USOIL": AssetConfig(
        symbol="USOIL",
        label="Crude Oil",
        enabled=False,
        contract_size=1000.0,                # 1000 barrels per lot
        pip_size=0.01,
        min_lot=0.01,
        max_lot=0.5,
        atr_pip_multiplier=100.0,
        risk_budget_pct=0.15,
        spread_typical_pct=0.0005,
        killzones_utc=((9, 11), (14, 16)),
        macro_relevance=("opec", "vixy", "geopolitical"),
        notes="Geopolitical-driven. Watch OPEC + GPR index closely.",
    ),
}


def get_asset(symbol: str) -> Optional[AssetConfig]:
    """Lookup asset config by symbol."""
    return DEFAULT_ASSETS.get(symbol)


def enabled_assets() -> list[AssetConfig]:
    """Return only enabled assets — what scanner should iterate."""
    return [a for a in DEFAULT_ASSETS.values() if a.enabled]


def total_risk_budget_pct() -> float:
    """Sum of risk_budget_pct across enabled assets. Should be ≤ 1.0
    unless leverage allows higher aggregate exposure."""
    return sum(a.risk_budget_pct for a in enabled_assets())


def validate_registry() -> list[str]:
    """Returns list of warnings if registry is malformed."""
    warnings = []
    if total_risk_budget_pct() > 1.0:
        warnings.append(
            f"Total risk budget {total_risk_budget_pct():.2f} > 1.0 — "
            f"sum of enabled assets exceeds full capital. Either reduce per-asset "
            f"risk_budget_pct or expect leverage."
        )
    for a in enabled_assets():
        if a.min_lot >= a.max_lot:
            warnings.append(f"{a.symbol}: min_lot {a.min_lot} >= max_lot {a.max_lot}")
    return warnings
