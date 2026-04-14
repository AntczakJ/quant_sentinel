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

BULLISH_WORDS = ["surge", "rally", "rise", "gain", "jump", "high", "bullish", "safe haven",
                 "demand", "buy", "support", "uptick", "soar", "breakout"]
BEARISH_WORDS = ["drop", "fall", "decline", "loss", "plunge", "low", "bearish", "sell",
                 "resistance", "downturn", "crash", "slump", "weakness"]


def _detect_sentiment(title: str) -> str:
    lower = title.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in lower)
    bear = sum(1 for w in BEARISH_WORDS if w in lower)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


def _detect_impact(title: str) -> str:
    high_impact = ["fed", "fomc", "cpi", "nfp", "powell", "interest rate", "tariff",
                   "recession", "employment", "gdp", "pce"]
    lower = title.lower()
    if any(w in lower for w in high_impact):
        return "high"
    if any(w in lower for w in ["gold", "xau", "dollar", "usd", "treasury", "bond"]):
        return "medium"
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
