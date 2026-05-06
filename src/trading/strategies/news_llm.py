"""src/trading/strategies/news_llm.py — LLM news as directional trigger.

2026-05-06 (Phase C.2 scaffold): gpt-4o-mini classifies incoming
Finnhub headlines into {direction, magnitude, decay_min}. Output used
as 5-30min position bias OR standalone trigger.

Per arxiv 2508.04975 (sentiment + technical fusion gives ~8% accuracy
boost) and frontiers/frai.2025 (LLMs improve intraday prediction).

NOT yet wired — needs:
  1. News pipeline (Finnhub already polled in src/data/news_feed.py)
  2. LLM classification cron (~60s interval)
  3. Decay/magnitude tracking
  4. Per-direction Platt calibration of LLM confidence

Default OFF until shadow-logged for 2 weeks (per Janek overfit rules).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from . import StrategySignal


@dataclass
class NewsClassification:
    direction: str  # "LONG" / "SHORT" / "NEUTRAL"
    magnitude: float  # 0.0 - 1.0
    decay_min: int  # how long signal stays active
    confidence: float  # LLM's self-rated certainty
    headline_hash: str
    timestamp: float


def classify_headline(headline: str, body: str = "") -> Optional[NewsClassification]:
    """Send headline to gpt-4o-mini for classification.

    Returns None on API failure or NEUTRAL classification.
    """
    try:
        from openai import OpenAI
        import os
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        prompt = f"""Classify this news headline for XAU/USD (gold) impact.

HEADLINE: {headline}
{f"BODY: {body[:500]}" if body else ""}

Output JSON only:
{{"direction": "LONG"|"SHORT"|"NEUTRAL",
  "magnitude": 0.0-1.0,
  "decay_min": 5-60,
  "confidence": 0.0-1.0,
  "reason": "brief"}}

Rules:
- LONG: bullish gold (USD weakness, fear, real yields down, geopolitical risk)
- SHORT: bearish gold (USD strength, real yields up, risk-on, equities rally)
- NEUTRAL: no directional impact
- decay_min: how long market reaction typically lasts (e.g. NFP=60, tweet=15, FOMC speech=30)
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content)

        direction = str(data.get("direction", "NEUTRAL")).upper()
        if direction not in ("LONG", "SHORT", "NEUTRAL"):
            return None

        import hashlib
        h = hashlib.sha256(headline.encode()).hexdigest()[:16]

        return NewsClassification(
            direction=direction,
            magnitude=float(data.get("magnitude", 0.5)),
            decay_min=int(data.get("decay_min", 30)),
            confidence=float(data.get("confidence", 0.5)),
            headline_hash=h,
            timestamp=time.time(),
        )
    except Exception:
        return None


def detect_setup(active_news: list[NewsClassification]) -> Optional[StrategySignal]:
    """Aggregate active (non-decayed) news classifications into a signal.

    Pass in the list of classifications still within their decay window.
    Returns dominant direction if magnitude-weighted vote is decisive.
    """
    if not active_news:
        return None

    long_score = 0.0
    short_score = 0.0
    now = time.time()

    for n in active_news:
        # Decay age (linear within decay_min)
        age_min = (now - n.timestamp) / 60.0
        if age_min > n.decay_min:
            continue
        decay_factor = 1.0 - (age_min / n.decay_min)
        weight = n.magnitude * n.confidence * decay_factor

        if n.direction == "LONG":
            long_score += weight
        elif n.direction == "SHORT":
            short_score += weight

    # Need clear winner with score > 0.3 minimum threshold
    if long_score > short_score and long_score > 0.3 and (long_score - short_score) > 0.15:
        return StrategySignal(
            strategy_name="news_llm",
            direction="LONG",
            confidence=min(0.9, long_score),
            reason=f"news_aggregate long={long_score:.2f} short={short_score:.2f}",
            metadata={"long_score": long_score, "short_score": short_score,
                      "active_count": len(active_news)},
        )
    if short_score > long_score and short_score > 0.3 and (short_score - long_score) > 0.15:
        return StrategySignal(
            strategy_name="news_llm",
            direction="SHORT",
            confidence=min(0.9, short_score),
            reason=f"news_aggregate long={long_score:.2f} short={short_score:.2f}",
            metadata={"long_score": long_score, "short_score": short_score,
                      "active_count": len(active_news)},
        )
    return None
