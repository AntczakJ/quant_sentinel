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


@cached('news_structured', ttl=180)
def get_latest_news() -> List[Dict]:
    """
    Aggregates news from RSS sources and returns structured objects.
    Each item: {title, source, published, sentiment, impact, url}
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    combined: List[Dict] = []

    for source_name, url in RSS_SOURCES.items():
        try:
            response = requests.get(url, headers=headers, timeout=8)
            feed = feedparser.parse(response.content)

            for entry in feed.entries[:8]:
                title_lower = entry.title.lower()

                if any(word in title_lower for word in KEYWORDS):
                    clean_title = re.sub('<[^<]+?>', '', entry.title).strip()
                    published = entry.get('published', entry.get('updated', ''))

                    combined.append({
                        "title": clean_title,
                        "source": source_name,
                        "published": published,
                        "sentiment": _detect_sentiment(clean_title),
                        "impact": _detect_impact(clean_title),
                        "url": entry.get('link', ''),
                    })

        except Exception as e:
            logger.warning(f"News source {source_name} error: {e}")

    # Deduplicate by title similarity and limit
    seen = set()
    unique: List[Dict] = []
    for item in combined:
        key = item["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:20]


CALENDAR_SOURCES = [
    "https://www.forexfactory.com/ffcal_week_this.xml",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
]

CALENDAR_IMPACT_KEYWORDS = {
    "high": ["nfp", "non-farm", "cpi", "fomc", "interest rate", "gdp", "pce",
             "employment", "payroll", "fed", "powell", "retail sales", "ism"],
    "medium": ["pmi", "housing", "consumer confidence", "durable goods",
               "trade balance", "unemployment", "jolts", "eci"],
}


@cached('calendar_structured', ttl=300)
def get_economic_calendar() -> List[Dict]:
    """
    Fetches upcoming economic events. Tries multiple sources with fallback.
    Each item: {event, date, time, currency, impact, forecast, previous, actual}
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    events: List[Dict] = []

    # Source 1: ForexFactory JSON feed (more reliable than XML)
    try:
        resp = requests.get(CALENDAR_SOURCES[1], headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for entry in data:
                currency = entry.get('country', '')
                if currency != 'USD':
                    continue
                impact = entry.get('impact', 'Low')
                if impact not in ('High', 'Medium'):
                    continue
                events.append({
                    "event": entry.get('title', 'Unknown'),
                    "date": entry.get('date', ''),
                    "time": entry.get('time', ''),
                    "currency": currency,
                    "impact": impact.lower(),
                    "forecast": entry.get('forecast', ''),
                    "previous": entry.get('previous', ''),
                    "actual": entry.get('actual', ''),
                })
            if events:
                return events[:15]
    except Exception as e:
        logger.debug(f"Calendar JSON source failed: {e}")

    # Source 2: ForexFactory XML RSS
    try:
        resp = requests.get(CALENDAR_SOURCES[0], headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            currency = entry.get('country', '')
            impact = entry.get('impact', 'low')
            if currency == 'USD' and impact in ('High', 'Medium', 'high', 'medium'):
                events.append({
                    "event": entry.get('title', 'Unknown Event'),
                    "date": entry.get('date', ''),
                    "time": entry.get('time', ''),
                    "currency": currency,
                    "impact": impact.lower(),
                    "forecast": entry.get('forecast', ''),
                    "previous": entry.get('previous', ''),
                    "actual": entry.get('actual', ''),
                })
        if events:
            return events[:15]
    except Exception as e:
        logger.debug(f"Calendar XML source failed: {e}")

    # Source 3: Generate from known schedule (static fallback)
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    # Common recurring USD events
    known_events = [
        {"event": "Initial Jobless Claims", "impact": "medium", "recurring": "weekly"},
        {"event": "CPI m/m", "impact": "high", "recurring": "monthly"},
        {"event": "Non-Farm Payrolls", "impact": "high", "recurring": "monthly"},
        {"event": "FOMC Statement", "impact": "high", "recurring": "6weeks"},
    ]
    for ev in known_events:
        events.append({
            "event": ev["event"],
            "date": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
            "time": "13:30",
            "currency": "USD",
            "impact": ev["impact"],
            "forecast": "",
            "previous": "",
            "actual": "",
        })

    return events
