import feedparser
import requests
import re
from src.core.cache import cached

from src.core.logger import logger


# Definiujemy kluczowe źródła dla Tradera Złota
RSS_SOURCES = {
    "Investing_Commodities": "https://www.investing.com/rss/news_95.rss",
    "Reuters_Business": "https://news.google.com/rss/search?q=Gold+Price+Reuters&hl=en-US&gl=US&ceid=US:en",
    "FXStreet_Gold": "https://www.fxstreet.com/rss/news/commodities/gold"
}
@cached('news', ttl=180)
def get_latest_news() -> str:
    """
    Agreguje newsy z wielu źródeł, filtruje je i przygotowuje głęboki kontekst dla AI.
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    combined_news = []
    
    # Słowa kluczowe, które nas interesują (szukamy korelacji)
    keywords = ["gold", "xau", "fed", "inflation", "cpi", "powell", "dollar", "usd", "yields", "interest rates"]

    for source_name, url in RSS_SOURCES.items():
        try:
            response = requests.get(url, headers=headers, timeout=8)
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries[:5]: # Bierzemy 5 najnowszych z każdego źródła
                title = entry.title.lower()
                
                # FILTR: Dodaj tylko jeśli news jest istotny dla złota/dolara
                if any(word in title for word in keywords):
                    # Usuwamy zbędne tagi HTML i czyścimy tekst
                    clean_title = re.sub('<[^<]+?>', '', entry.title)
                    combined_news.append(f"[{source_name}] {clean_title}")
                    
        except Exception as e:
            logger.warning(f"⚠️ Błąd źródła {source_name}: {e}")

    if not combined_news:
        return "Brak krytycznych newsów (Rynek stabilny/oczekujący)."

    # Sortujemy i bierzemy 8 najbardziej unikalnych/świeżych informacji
    unique_news = list(set(combined_news))[:8]
    return "\n".join(unique_news)

@cached('calendar', ttl=300)
def get_economic_calendar() -> str:
    """
    Pobiera nadchodzące wydarzenia High Impact z ForexFactory.
    """
    ff_url = "https://www.forexfactory.com/ffcal_week_this.xml"  # RSS Kalendarza
    headers = {'User-Agent': 'Mozilla/5.0'}
    events = []

    try:
        response = requests.get(ff_url, headers=headers, timeout=10)
        # Parsujemy XML ręcznie lub przez feedparser (FF używa specyficznego formatu)
        feed = feedparser.parse(response.content)

        from datetime import datetime
        now = datetime.now()

        for entry in feed.entries:
            # Filtrujemy tylko USD (Dolar) i High Impact
            if entry.get('country') == 'USD' and entry.get('impact') == 'High':
                event_time = entry.get('date') + " " + entry.get('time')
                events.append(f"⚠️ {entry.title} ({event_time})")

        return "\n".join(events[:3])  # Zwracamy 3 najbliższe ważne wydarzenia
    except (requests.RequestException, AttributeError, ValueError, KeyError):
        return "Brak danych z kalendarza."