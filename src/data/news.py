import feedparser
import requests
import re
from typing import List, Dict
from src.core.cache import cached
from src.core.logger import logger


# Key RSS sources for Gold Trader
RSS_SOURCES = {
    "Investing": "https://www.investing.com/rss/news_95.rss",
    "Reuters": "https://news.google.com/rss/search?q=Gold+Price+Reuters&hl=en-US&gl=US&ceid=US:en",
    "FXStreet": "https://www.fxstreet.com/rss/news/commodities/gold"
}

KEYWORDS = ["gold", "xau", "fed", "inflation", "cpi", "powell", "dollar", "usd",
            "yields", "interest rates", "tariff", "trade war", "recession", "employment",
            "nfp", "fomc", "treasury", "bond", "central bank"]

# Regex keyword-based sentiment/impact detection REMOVED 2026-04-24.
# Research (MDPI 1.86M-headline study, Permutable.ai, arXiv) shows headline
# sentiment via word-counting has "no robust predictive power" for gold
# next-day moves. Our previous BULLISH_WORDS / BEARISH_WORDS approach was
# exactly the 2010-era NLP pattern the research dismisses. Example failure:
# "gold fall(s) to support" → classified BEARISH, but it's actually a
# neutral/buy-signal headline. News sentiment should come from a calibrated
# LLM or from event calendar + price confirmation, not keyword counting.
# See docs/research/2026-04-24_xau_news_research.md for the replacement plan.
#
# 2026-05-04: LLM-based sentiment shipped. Uses OpenAI gpt-4o-mini via
# existing src.integrations.ai_engine.client. Cached per-title to avoid
# spam. Env QUANT_NEWS_LLM=1 enables, default OFF (fallback to neutral).
# Cheap: ~$0.0001 per headline, 30 articles/cycle × 5min cycles = ~$0.40/day.
#
# Cache stores (verdict, timestamp). 24h TTL — same headline re-asked the
# next day re-queries (regime/context may have shifted). Without TTL, a
# Monday verdict survives until process restart, masking fresh sentiment.
import time as _time
# 2026-05-04: switched FIFO → LRU per 6-agent integration audit.
# OrderedDict + move_to_end on read keeps frequently-accessed headlines
# in cache (e.g., NFP coverage repeated across cycles). FIFO would
# evict hot headlines first, causing duplicate LLM calls.
from collections import OrderedDict as _OrderedDict
_LLM_SENTIMENT_CACHE: "_OrderedDict[str, tuple[str, float]]" = _OrderedDict()
_LLM_SENTIMENT_CACHE_MAX = 1000
_LLM_SENTIMENT_CACHE_TTL = 86400  # 24h


def _detect_sentiment_llm(title: str) -> str:
    """LLM-based sentiment classification of news article title.

    Returns: 'bullish' | 'bearish' | 'neutral'

    Cached by title with 24h TTL — same article re-asked within a day uses
    the cached verdict; older entries are re-queried.
    Falls back to 'neutral' on any error (network, missing key, parse fail).
    """
    if not title:
        return "neutral"
    title = title.strip()
    cached = _LLM_SENTIMENT_CACHE.get(title)
    now = _time.time()
    if cached is not None:
        verdict, ts = cached
        if now - ts < _LLM_SENTIMENT_CACHE_TTL:
            # LRU bump: move-to-end marks as recently-used
            _LLM_SENTIMENT_CACHE.move_to_end(title)
            return verdict
        # Expired — fall through to re-query

    # LRU eviction: drop oldest 25% when cap reached. OrderedDict's
    # iter order is insertion-order; popitem(last=False) drops oldest
    # (LRU) — keeps frequently-accessed headlines.
    if len(_LLM_SENTIMENT_CACHE) >= _LLM_SENTIMENT_CACHE_MAX:
        for _ in range(_LLM_SENTIMENT_CACHE_MAX // 4):
            try:
                _LLM_SENTIMENT_CACHE.popitem(last=False)
            except KeyError:
                break

    try:
        from src.integrations.ai_engine import client
        if client is None:
            return "neutral"
        # Cheap classification call
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": ("You classify XAU/USD (gold) news headline sentiment. "
                             "Reply with EXACTLY ONE WORD: bullish, bearish, or neutral. "
                             "Bullish = supports higher gold price (weak USD, dovish Fed, "
                             "geopolitical risk, inflation up). Bearish = supports lower gold "
                             "(strong USD, hawkish Fed, risk-on, deflation). Neutral = ambiguous "
                             "or no clear directional implication.")},
                {"role": "user", "content": title},
            ],
            max_tokens=4,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip().lower()
        # Normalize to expected vocab
        if raw.startswith("bull"):
            result = "bullish"
        elif raw.startswith("bear"):
            result = "bearish"
        else:
            result = "neutral"
    except Exception as e:
        logger.debug(f"_detect_sentiment_llm failed for '{title[:60]}': {e}")
        result = "neutral"
    _LLM_SENTIMENT_CACHE[title] = (result, now)
    return result


def _detect_sentiment(title: str) -> str:
    """Sentiment classifier dispatcher. When QUANT_NEWS_LLM=1, calls
    LLM scorer; else returns 'neutral' stub (legacy behavior)."""
    import os as _os
    if _os.environ.get("QUANT_NEWS_LLM") == "1":
        return _detect_sentiment_llm(title)
    return "neutral"


def _detect_impact(title: str) -> str:
    """Deprecated stub. Returns low — rely on economic calendar + explicit tier mapping instead."""
    return "low"


def _fetch_rss(source_name: str, url: str, headers: Dict) -> List[Dict]:
    """Fetch and parse one RSS source. Returns list of structured news dicts.
    Never raises — errors are logged and yield an empty list so one bad
    feed can't poison the aggregate."""
    out: List[Dict] = []
    try:
        response = requests.get(url, headers=headers, timeout=8)
        feed = feedparser.parse(response.content)
        for entry in feed.entries[:8]:
            title_lower = entry.title.lower()
            if any(word in title_lower for word in KEYWORDS):
                clean_title = re.sub('<[^<]+?>', '', entry.title).strip()
                published = entry.get('published', entry.get('updated', ''))
                out.append({
                    "title": clean_title,
                    "source": source_name,
                    "published": published,
                    "sentiment": _detect_sentiment(clean_title),
                    "impact": _detect_impact(clean_title),
                    "url": entry.get('link', ''),
                })
    except Exception as e:
        logger.warning(f"News source {source_name} error: {e}")
    return out


@cached('news_structured', ttl=180)
def get_latest_news() -> List[Dict]:
    """
    Aggregates news from RSS sources and returns structured objects.
    Each item: {title, source, published, sentiment, impact, url}

    Fetches feeds in parallel via ThreadPoolExecutor — previously serial
    fetch took ~3*8s worst case (total timeout budget) and blocked the
    endpoint while any one source was slow. Parallel fetch bounds latency
    at the slowest single source (~8s), which is the common case anyway.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    headers = {'User-Agent': 'Mozilla/5.0'}
    combined: List[Dict] = []

    with ThreadPoolExecutor(max_workers=len(RSS_SOURCES)) as pool:
        futures = {
            pool.submit(_fetch_rss, name, url, headers): name
            for name, url in RSS_SOURCES.items()
        }
        for fut in as_completed(futures):
            try:
                combined.extend(fut.result(timeout=10))
            except Exception as e:
                logger.warning(f"News fetch future failed ({futures[fut]}): {e}")

    # Deduplicate by title similarity and limit
    seen = set()
    unique: List[Dict] = []
    for item in combined:
        key = item["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:20]


CALENDAR_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_XML_URL = "https://www.forexfactory.com/ffcal_week_this.xml"

# Majors + gold-relevant crosses. DXY driven by EUR/JPY/GBP/CAD/CHF/SEK, so
# these currencies' events move XAU/USD even if not USD-denominated. "All" covers
# IMF/G20/OPEC meetings.
CALENDAR_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CNY", "All"}

# Grace window: events within last 6h kept as "just happened" (actual data may
# still be arriving). Anything older is filtered out.
_PAST_GRACE_HOURS = 6

# Hard cap on events returned — 80 covers ~1 week of majors at all impact levels
# without overwhelming the UI.
_MAX_EVENTS = 80


def _parse_event_date(date_str: str):
    """Parse ForexFactory ISO date into tz-aware UTC datetime. Returns None on
    failure so callers can skip the row instead of crashing the endpoint."""
    from datetime import datetime, timezone
    if not date_str:
        return None
    try:
        ts = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


@cached('calendar_structured', ttl=300)
def get_economic_calendar() -> List[Dict]:
    """
    Fetches economic events for the current week from ForexFactory.

    Returns events within [now - 6h, +inf) across all majors, sorted ascending.
    The frontend splits into upcoming vs recent based on countdown.

    Each item: {event, date, time, currency, impact, forecast, previous, actual,
                date_utc, ts_utc} where date_utc is ISO string and ts_utc is
                unix epoch seconds (frontend uses ts_utc to avoid re-parsing).
    """
    from datetime import datetime, timezone, timedelta
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_PAST_GRACE_HOURS)
    events: List[Dict] = []

    def _add_entry(entry: Dict, from_xml: bool = False) -> None:
        currency = (entry.get('country') or '').strip()
        if currency and currency not in CALENDAR_CURRENCIES:
            return
        date_str = entry.get('date', '')
        dt = _parse_event_date(date_str)
        if dt is None or dt < cutoff:
            return
        impact_raw = (entry.get('impact') or 'Low').strip()
        events.append({
            "event": entry.get('title', 'Unknown Event'),
            "date": date_str,
            "time": entry.get('time', ''),
            "currency": currency or 'All',
            "impact": impact_raw.lower(),
            "forecast": entry.get('forecast', ''),
            "previous": entry.get('previous', ''),
            "actual": entry.get('actual', ''),
            "date_utc": dt.isoformat(),
            "ts_utc": int(dt.timestamp()),
        })

    # Source 1: FairEconomy JSON mirror — canonical feed, ~100 events/week
    try:
        resp = requests.get(CALENDAR_JSON_URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            for entry in resp.json():
                _add_entry(entry)
    except Exception as e:
        logger.debug(f"Calendar JSON source failed: {e}")

    # Source 2: ForexFactory XML — fallback if JSON feed down
    if not events:
        try:
            resp = requests.get(CALENDAR_XML_URL, headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                _add_entry(dict(entry), from_xml=True)
        except Exception as e:
            logger.debug(f"Calendar XML source failed: {e}")

    # Source 3: Static fallback — only if everything else failed. Covers the
    # next ~2 weeks with recurring USD events. Impact-tagged so UI still
    # renders meaningfully during an outage.
    if not events:
        known = [
            ("Initial Jobless Claims", "medium", 2),
            ("CPI m/m", "high", 5),
            ("Non-Farm Payrolls", "high", 7),
            ("FOMC Statement", "high", 10),
            ("Retail Sales m/m", "medium", 4),
            ("PPI m/m", "medium", 6),
        ]
        for title, impact, days in known:
            dt = (now + timedelta(days=days)).replace(hour=12, minute=30, second=0, microsecond=0)
            events.append({
                "event": title,
                "date": dt.isoformat(),
                "time": dt.strftime("%H:%M"),
                "currency": "USD",
                "impact": impact,
                "forecast": "",
                "previous": "",
                "actual": "",
                "date_utc": dt.isoformat(),
                "ts_utc": int(dt.timestamp()),
            })

    events.sort(key=lambda e: e["ts_utc"])
    return events[:_MAX_EVENTS]


# Event tier mapping (2026-04-24 — from research synthesis).
# Tier 1: flat ±15 min, trade second rotation only.
# Tier 2: risk halve ±10 min.
# Tier 3: trade normally; log warning.
# Keywords match the `event` field (case-insensitive substring).
EVENT_TIERS = {
    "tier1": [
        "non-farm payrolls", "nfp",  # US Employment Situation
        "cpi", "core cpi",           # Consumer Price Index
        "fomc", "federal funds",      # Fed rate decision / statement
        "fomc statement", "fomc minutes",
        "pce", "core pce",            # Personal Consumption Expenditures (Fed's preferred)
    ],
    "tier2": [
        "ppi", "producer prices",
        "adp", "nonfarm employment change",
        "retail sales",
        "jobless claims", "initial jobless",
        "gdp",                        # Advance/revision
        "unemployment rate",
    ],
    "tier3": [
        "powell", "fed chair",
        "ecb", "draghi", "lagarde",
        "boj", "bank of japan",
        "snb", "swiss",
        "fed speaker",                # generic catch for Williams, Waller, etc.
    ],
}


def classify_event_tier(event_text: str) -> str | None:
    """Classify an economic event into tier1/tier2/tier3 or None.

    Used by the scanner event guard to apply differential handling:
      tier1 → hard block ±15 min, trade only post-15m-candle-close confirm
      tier2 → halve risk ±10 min
      tier3 → normal with warning log
    """
    if not event_text:
        return None
    s = event_text.lower()
    for tier, keywords in EVENT_TIERS.items():
        if any(k in s for k in keywords):
            return tier
    return None


def get_recent_tier1_events(minutes_window: int = 60) -> list:
    """Tier 1 events that already happened within the past `minutes_window`.

    Used by the scanner second-rotation entry path: after a tier-1 event,
    wait for a 15m candle to close in the direction of the move and trade
    the continuation. Research-backed (post-event reaction window 15-60 min
    is the highest-edge timing for retail; first 5 min is HFT territory).

    Returns list of events that fired in [now - window, now] sorted newest
    first. Empty list = no recent tier-1 → no second-rotation opportunity.
    """
    out: list = []
    try:
        from datetime import datetime, timezone, timedelta
        events = get_economic_calendar() or []
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=minutes_window)
        for ev in events:
            date_str = ev.get("date", "")
            if not date_str:
                continue
            try:
                ts = date_str.replace("Z", "+00:00")
                ev_dt = datetime.fromisoformat(ts)
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                ev_dt = ev_dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
            if not (window_start <= ev_dt <= now):
                continue
            tier = classify_event_tier(ev.get("event", ""))
            if tier == "tier1":
                ev_with_age = dict(ev)
                ev_with_age["minutes_ago"] = round((now - ev_dt).total_seconds() / 60, 1)
                out.append(ev_with_age)
    except Exception as e:
        logger.warning(f"get_recent_tier1_events failed: {e}")
    out.sort(key=lambda e: e.get("minutes_ago", 0))
    return out


def get_imminent_events_by_tier(minutes_window: int = 15) -> dict:
    """Group imminent events by tier1/tier2/tier3.

    Returns {'tier1': [ev,...], 'tier2': [...], 'tier3': [...]}.
    Drop-in helper for scanner event_guard which wants tier-aware handling.
    """
    out: dict = {"tier1": [], "tier2": [], "tier3": []}
    # Backtest bypass: imminent-window comparison uses real wall-clock UTC,
    # so any sim cycle whose real time happens to land within ±15 min of a
    # real upcoming Tier 1 event would be hard-blocked. We have no
    # historical news DB for 2024, so the honest backtest behaviour is
    # "no events known" — let the simulator run.
    import os as _os_eg
    if _os_eg.environ.get("QUANT_BACKTEST_MODE"):
        return out
    try:
        from datetime import datetime, timezone, timedelta
        events = get_economic_calendar() or []
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=minutes_window)
        for ev in events:
            date_str = ev.get("date", "")
            if not date_str:
                continue
            try:
                ts = date_str.replace("Z", "+00:00")
                ev_dt = datetime.fromisoformat(ts)
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                ev_dt = ev_dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
            if not (now <= ev_dt <= window_end):
                continue
            tier = classify_event_tier(ev.get("event", ""))
            if tier in out:
                out[tier].append(ev)
    except Exception as e:
        logger.warning(f"get_imminent_events_by_tier: fail-close with error {e}")
        # Fail closed — signal tier1 so scanner blocks
        out["tier1"] = [{"event": "CALENDAR_ERROR", "impact": "high", "_synthetic": True}]
    return out


def requires_clear_calendar(minutes_window: int = 15, impacts: tuple = ("high",)):
    """Decorator: skip a trade-open function if a high-impact event is imminent.

    Usage:
        @requires_clear_calendar(minutes_window=15)
        def open_trade(...): ...

    Wrapped function returns None (instead of executing) when event guard
    fires. Logs the blocking event name. Soft-fails on calendar API errors
    (does NOT block trading if calendar fetch itself fails).
    """
    def _decorator(fn):
        import functools
        @functools.wraps(fn)
        def _wrapped(*args, **kwargs):
            imminent = get_imminent_high_impact_events(minutes_window=minutes_window, impacts=impacts)
            if imminent:
                titles = ", ".join(e.get("event", "?") for e in imminent[:2])
                logger.info(f"[EVENT GUARD] {fn.__name__} blocked — imminent event: {titles}")
                return None
            return fn(*args, **kwargs)
        _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        return _wrapped
    return _decorator


def get_imminent_high_impact_events(minutes_window: int = 15,
                                    impacts: tuple = ("high",)) -> List[Dict]:
    """Return high-impact events scheduled within [now, now + minutes_window].

    Used by trade pipeline to auto-mute before NFP/CPI/FOMC (gold can move
    2-3% in 30 sec, hitting SL before any signal makes sense).

    Args:
      minutes_window: look-ahead window in minutes (default 15)
      impacts: which impact levels to include (default: just 'high')

    Returns list of matching events. Empty list = safe to trade.
    """
    from datetime import datetime, timezone, timedelta
    # Backtest bypass: see get_imminent_events_by_tier above. Returning [] is
    # the "safe to trade" signal — no fail-closed sentinel because the
    # backtest provider never errors here.
    import os as _os_eg
    if _os_eg.environ.get("QUANT_BACKTEST_MODE"):
        return []
    try:
        events = get_economic_calendar() or []
    except Exception as e:
        # FAIL-CLOSED (changed 2026-04-14): previously returned [] meaning
        # "no events, safe to trade" which lets trades through during NFP/
        # CPI/FOMC if the calendar API is down. Those events move gold 2-3%
        # in seconds and hit SL instantly. Returning a synthetic sentinel
        # event causes requires_clear_calendar to BLOCK the trade — the
        # safer default when we can't see the calendar.
        logger.warning(f"Event guard: calendar fetch failed ({e}) — "
                       f"FAIL-CLOSED, blocking new trades this cycle")
        now = datetime.now(timezone.utc)
        return [{
            "event": "CALENDAR_FETCH_FAILED",
            "impact": "high",
            "date": now.isoformat(),
            "_synthetic": True,
        }]

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=minutes_window)
    matches: List[Dict] = []

    for ev in events:
        impact = (ev.get("impact") or "").lower()
        if impact not in impacts:
            continue
        date_str = ev.get("date", "")
        if not date_str:
            continue
        try:
            # ISO 8601 with timezone — most common case
            ts = date_str.replace("Z", "+00:00")
            ev_dt = datetime.fromisoformat(ts)
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            ev_dt = ev_dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

        if now <= ev_dt <= window_end:
            matches.append(ev)

    return matches
