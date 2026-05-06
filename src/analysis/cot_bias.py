"""src/analysis/cot_bias.py — CFTC Commitments of Traders extreme-divergence.

2026-05-06 (Phase A.4): COT extreme-divergence weekly bias.
When |MM_pct - Producer_pct| > 80 (3-yr percentile), a 1-week directional
bias toward the producer side appears reliably. Producers are smart money;
managed-money is contrarian at extremes.

Pull weekly Saturday from CFTC. Cached locally (data/cot_cache.pkl
already exists).

Source: tradingster.com/cot/legacy-futures/088691 (Gold COMEX disaggregated)
+ jinlow.substack.com/p/understanding-the-cftc-cot-report
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


def get_cot_extreme_bias() -> dict:
    """Compute current COT extreme-divergence bias for gold.

    Reuses existing src.data.cot_data infrastructure.

    Returns:
        signal: -1 (short bias) | 0 (no extreme) | +1 (long bias)
        mm_net_pct: managed-money net positioning percentile (3yr)
        producer_net_pct: producer net positioning percentile (3yr)
        divergence: |mm_pct - producer_pct| in percentile points
    """
    try:
        from src.data.cot_data import get_gold_cot_signal
        signal_data = get_gold_cot_signal()
        if not signal_data:
            return {"signal": 0, "mm_net_pct": None,
                    "producer_net_pct": None, "divergence": None}

        # Existing function returns simple {-1, 0, +1} via signal key.
        # Promote to extreme-divergence rule:
        #   when divergence > 80 percentile → use signal direction; else 0
        base_signal = signal_data.get("signal", 0)
        mm_pct = signal_data.get("mm_net_pct")
        producer_pct = signal_data.get("producer_net_pct")

        divergence = None
        if mm_pct is not None and producer_pct is not None:
            divergence = abs(float(mm_pct) - float(producer_pct))

        # Only honor signal when divergence extreme (≥80pp)
        if divergence is not None and divergence >= 80:
            return {
                "signal": base_signal,
                "mm_net_pct": mm_pct,
                "producer_net_pct": producer_pct,
                "divergence": round(divergence, 1),
            }
        # Below threshold — no edge
        return {
            "signal": 0,
            "mm_net_pct": mm_pct,
            "producer_net_pct": producer_pct,
            "divergence": round(divergence, 1) if divergence else None,
        }
    except Exception:
        return {"signal": 0, "mm_net_pct": None,
                "producer_net_pct": None, "divergence": None}
