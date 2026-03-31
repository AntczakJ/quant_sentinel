"""
data_collector.py — pobieranie newsów z wielu kanałów RSS.

Różnica od news.py:
  - news.py    → pobiera z jednego kanału, zwraca sformatowany string
  - data_collector.py → pobiera z wielu kanałów, zwraca listę słowników

Ten moduł jest przeznaczony do integracji z fusion_engine.py i sentiment.py,
gdzie potrzebny jest dostęp do tytułu i linku każdego newsa osobno.
"""

import feedparser


def get_latest_news() -> list[dict]:
    """
    Pobiera najnowsze wiadomości finansowe z kilku kanałów RSS Investing.com.

    Kanały RSS:
      - news_95.rss     : Commodities (złoto, ropa, srebro)
      - market_overview : Przegląd rynkowy (indeksy, waluty)

    Zwraca:
        Listę słowników, każdy z kluczami:
          - title : tytuł newsa
          - link  : URL do pełnego artykułu

        Z każdego kanału pobieranych jest maksymalnie 5 najnowszych newsów.
        Łącznie do 10 newsów jeśli oba kanały działają poprawnie.
        Lista może być pusta jeśli wszystkie kanały zwróciły błąd.
    """
    rss_urls = [
        "https://www.investing.com/rss/news_95.rss",       # Commodities
        "https://www.investing.com/rss/market_overview.rss"  # Market Overview
    ]

    all_news = []

    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                all_news.append({
                    "title": entry.title,
                    "link": entry.link
                })
        except Exception as e:
            print(f"Błąd pobierania RSS ({url}): {e}")

    return all_news
