"""src/trading/strategies/ — multi-strategy registry.

2026-05-06 (Phase C scaffold): foundation for running multiple
uncorrelated strategies side-by-side. Each strategy is a self-contained
module with: detect_setup(df) → Optional[StrategySignal], + metadata.

Currently scaffolded (not active):
  - mean_reversion: intraday range-fade
  - vol_breakout: ATR-percentile breakout
  - news_llm: LLM news-driven directional bias
  - smc_primary: existing main scanner (unchanged behavior)

Aggregator (future): runs all enabled strategies per cycle, voted by
weights derived from rolling Sharpe per strategy.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategySignal:
    """Output from any strategy detect function."""
    strategy_name: str
    direction: str  # "LONG" / "SHORT" / "NONE"
    confidence: float  # 0.0 - 1.0
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    reason: str = ""
    metadata: dict = None
