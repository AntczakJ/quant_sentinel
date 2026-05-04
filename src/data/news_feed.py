"""
src/news_feed.py — Real-time Financial News Pipeline

Sources:
  1. Finnhub Market News (real-time, 60 calls/min free)
     - General market news (100 latest articles)
     - Forex-specific news
     - Gold/commodity filtering by keyword

  2. FinBERT Sentiment Classification
     - Classifies each headline as bullish/bearish/neutral for gold
     - Scores from -1 (very bearish) to +1 (very bullish)

  3. News Impact Assessment
     - High impact: Fed, CPI, NFP, FOMC, interest rates
     - Medium impact: inflation, employment, GDP, trade war
     - Low impact: general market commentary

Pipeline: Fetch → Filter gold-relevant → Classify sentiment → Aggregate → Signal

Usage:
    from src.data.news_feed import get_gold_news_signal
    signal = get_gold_news_signal()
"""

import os
import time
import datetime
import re
from typing import Optional, Dict, List
from dotenv import load_dotenv
from src.core.logger import logger

load_dotenv()

_NEWS_CACHE: Dict = {"data": None, "ts": 0}
_NEWS_CACHE_TTL = 300  # 5 minutes

# Keywords for gold-relevance filtering (case-insensitive)
_GOLD_KEYWORDS = [
    'gold', 'xau', 'precious metal', 'bullion', 'safe haven', 'safe-haven',
    'treasury', 'yield', 'real yield', 'tips',
    'federal reserve', 'fed ', 'fomc', 'powell', 'rate cut', 'rate hike',
    'interest rate', 'monetary policy', 'quantitative',
    'inflation', 'cpi', 'pce', 'consumer price',
    'dollar', 'usd', 'dxy', 'greenback',
    'geopolitic', 'war', 'conflict', 'sanction', 'tariff', 'trade war',
    'nfp', 'non-farm', 'payroll', 'employment', 'jobs',
    'gdp', 'recession', 'economic growth',
    'central bank', 'ecb', 'boj', 'pboc', 'rba',
    'oil', 'commodity', 'silver', 'mining',
]

# High-impact keywords (trigger stronger signal weight)
_HIGH_IMPACT_KEYWORDS = [
    'fed ', 'fomc', 'powell', 'rate cut', 'rate hike', 'interest rate',
    'cpi', 'inflation', 'nfp', 'non-farm', 'payroll',
    'war', 'nuclear', 'invasion', 'sanctions',
    'recession', 'crisis', 'crash', 'collapse',
]

# Gold-bullish keywords
_BULLISH_KEYWORDS = [
    'safe haven', 'safe-haven', 'risk-off', 'uncertainty', 'fear',
    'rate cut', 'dovish', 'easing', 'stimulus', 'accommodation',
    'inflation rise', 'inflation surge', 'cpi above', 'cpi beat',
    'dollar weak', 'dollar fall', 'dollar drop', 'greenback slide',
    'geopolitical risk', 'war', 'conflict', 'escalat',
    'gold surge', 'gold rally', 'gold gain', 'gold climb', 'gold hit',
    'buy gold', 'gold demand', 'central bank buy',
    'recession', 'slowdown', 'contraction',
]

# Gold-bearish keywords
_BEARISH_KEYWORDS = [
    'risk-on', 'risk appetite', 'optimism',
    'rate hike', 'hawkish', 'tightening', 'restrictive',
    'inflation cool', 'inflation ease', 'cpi below', 'cpi miss',
    'dollar strong', 'dollar surge', 'dollar rally', 'greenback gain',
    'gold fall', 'gold drop', 'gold decline', 'gold slump', 'gold retreat',
    'sell gold', 'gold sell-off',
    'strong job', 'strong employment', 'nfp beat', 'payroll beat',
    'gdp growth', 'economic growth', 'expansion',
    'ceasefire', 'peace', 'de-escalat',
]


def _is_gold_relevant(headline: str) -> bool:
    """Check if headline is relevant to gold trading."""
    hl = headline.lower()
    return any(kw in hl for kw in _GOLD_KEYWORDS)


def _classify_headline(headline: str) -> Dict:
    """
    Classify headline sentiment for gold.

    2026-05-04: env QUANT_NEWS_LLM=1 routes through OpenAI gpt-4o-mini
    classifier in src.data.news._detect_sentiment_llm. Maps {bullish,
    bearish, neutral} → score {+1.0, -1.0, 0.0}. Cached per-title.
    Falls back to keyword path on LLM error/disabled.

    Returns: {"score": float (-1 to +1), "impact": "high"|"medium"|"low"}
    """
    import os as _os
    hl = headline.lower()

    # Impact level (unchanged — keyword-based, low cost, fine)
    if any(kw in hl for kw in _HIGH_IMPACT_KEYWORDS):
        impact = "high"
    elif _is_gold_relevant(hl):
        impact = "medium"
    else:
        impact = "low"

    # Sentiment via LLM if enabled, else keyword fallback
    score = None
    if _os.environ.get("QUANT_NEWS_LLM") == "1":
        try:
            from src.data.news import _detect_sentiment_llm
            verdict = _detect_sentiment_llm(headline)
            if verdict == "bullish":
                score = 1.0
            elif verdict == "bearish":
                score = -1.0
            else:
                score = 0.0
        except Exception:
            score = None  # fallback to keyword path

    if score is None:
        # Keyword fallback (legacy path, kept for resilience)
        bullish_hits = sum(1 for kw in _BULLISH_KEYWORDS if kw in hl)
        bearish_hits = sum(1 for kw in _BEARISH_KEYWORDS if kw in hl)
        total = bullish_hits + bearish_hits
        if total == 0:
            score = 0.0
        else:
            score = (bullish_hits - bearish_hits) / total

    # Boost score for high-impact news
    if impact == "high":
        score *= 1.5

    score = max(-1.0, min(1.0, score))

    return {"score": round(score, 3), "impact": impact}


def fetch_finnhub_news() -> List[Dict]:
    """
    Fetch latest market news from Finnhub, filter for gold relevance.
    Returns list of classified news items.
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        return []

    try:
        import finnhub
        client = finnhub.Client(api_key=api_key)

        # Fetch general market news (max 100)
        raw_news = client.general_news('general', min_id=0)
        if not raw_news:
            return []

        # Filter gold-relevant and classify
        results = []
        for article in raw_news:
            headline = article.get('headline', '')
            if not _is_gold_relevant(headline):
                continue

            classification = _classify_headline(headline)

            # Time decay: older news gets less weight
            article_time = article.get('datetime', 0)
            if article_time:
                age_hours = (time.time() - article_time) / 3600
                decay = max(0.1, 1.0 - (age_hours / 48))  # half-weight at 24h, 10% at 48h
            else:
                decay = 0.5

            results.append({
                "headline": headline[:200],
                "source": article.get('source', 'unknown'),
                "url": article.get('url', ''),
                "timestamp": datetime.datetime.fromtimestamp(article_time).isoformat() if article_time else None,
                "age_hours": round(age_hours, 1) if article_time else None,
                "score": classification["score"],
                "impact": classification["impact"],
                "decay": round(decay, 2),
                "weighted_score": round(classification["score"] * decay, 3),
            })

        # Sort by impact (high first) then by recency
        results.sort(key=lambda x: (
            {"high": 0, "medium": 1, "low": 2}.get(x["impact"], 3),
            -(x.get("age_hours") or 999)
        ))

        return results

    except ImportError:
        logger.debug("[NEWS] finnhub-python not installed")
        return []
    except Exception as e:
        logger.warning(f"[NEWS] Finnhub fetch failed: {e}")
        return []


def get_gold_news_signal() -> Dict:
    """
    Aggregate gold news into a single trading signal.

    Returns:
      {
        "signal": -1|0|1,           # -1=bullish, 0=neutral, 1=bearish for gold
        "signal_text": "...",
        "avg_score": float,         # weighted average sentiment (-1 to +1)
        "news_count": int,          # gold-relevant articles found
        "high_impact_count": int,
        "headlines": [...],         # top 5 headlines with scores
      }
    """
    # Backtest mode: don't leak LIVE sentiment (today's news) into historical
    # scans — it's not reconstructible and would be pure look-ahead bias.
    # Return neutral, forces strategy to decide without news input.
    import os as _os
    if _os.environ.get("QUANT_BACKTEST_MODE") == "1":
        return {
            "signal": 0,
            "signal_text": "backtest neutral (no historical sentiment)",
            "avg_score": 0.0,
            "news_count": 0,
            "high_impact_count": 0,
            "headlines": [],
        }

    # Cache check
    now = time.time()
    if _NEWS_CACHE["data"] and (now - _NEWS_CACHE["ts"]) < _NEWS_CACHE_TTL:
        return _NEWS_CACHE["data"]

    articles = fetch_finnhub_news()

    if not articles:
        result = {"signal": 0, "signal_text": "no news data", "news_count": 0,
                  "high_impact_count": 0, "avg_score": 0, "headlines": []}
        return result

    # Weighted average sentiment (impact + time-decay weighted)
    impact_weights = {"high": 3.0, "medium": 1.5, "low": 0.5}
    total_weight = 0
    weighted_sum = 0

    for a in articles:
        w = impact_weights.get(a["impact"], 1.0) * a.get("decay", 1.0)
        weighted_sum += a["score"] * w
        total_weight += w

    avg_score = weighted_sum / total_weight if total_weight > 0 else 0
    high_impact = sum(1 for a in articles if a["impact"] == "high")

    # Signal generation
    if avg_score > 0.15:
        signal = -1  # net bullish sentiment → gold bullish
        signal_text = f"bullish ({avg_score:+.2f})"
    elif avg_score < -0.15:
        signal = 1   # net bearish sentiment → gold bearish
        signal_text = f"bearish ({avg_score:+.2f})"
    else:
        signal = 0
        signal_text = f"neutral ({avg_score:+.2f})"

    result = {
        "signal": signal,
        "signal_text": signal_text,
        "avg_score": round(avg_score, 3),
        "news_count": len(articles),
        "high_impact_count": high_impact,
        "headlines": [
            {"headline": a["headline"], "source": a["source"],
             "score": a["score"], "impact": a["impact"]}
            for a in articles[:7]
        ],
    }

    _NEWS_CACHE["data"] = result
    _NEWS_CACHE["ts"] = now

    logger.info(
        f"[NEWS] Gold news: {len(articles)} articles, "
        f"{high_impact} high-impact, avg_score={avg_score:+.3f}, signal={signal_text}"
    )

    return result
