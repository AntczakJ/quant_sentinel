"""
logic.py — makroekonomiczna logika korelacji DXY/XAU.

Odpowiada za:
  - Interpretację wpływu sentymentu newsów na rynek złota i dolara
  - Wykrywanie kluczowych słów (FED, interest rate, gold, xau)
  - Generowanie sugestii tradingowych na podstawie korelacji makro

Logika korelacji:
  - Silniejszy dolar (DXY ↗) → złoto spada (XAU/USD ↘)
  - Słabszy dolar (DXY ↘) → złoto rośnie (XAU/USD ↗)
  - Newsy o podwyżkach stóp (hawkish FED) → byczy dla dolara, niedźwiedzi dla złota
  - Newsy o cięciach stóp (dovish FED) → niedźwiedzi dla dolara, byczy dla złota

Moduł jest używany przez fusion_engine.py jako część analizy makroekonomicznej.
"""


def interpret_impact(sentiment: dict, text: str, prices: dict) -> dict:
    """
    Interpretuje wpływ sentymentu newsa na rynki złota i dolara.

    Parametry:
        sentiment — słownik z wynikiem sentymentu, musi zawierać klucz 'label'
                    z wartością "Bullish", "Bearish" lub "Neutral"
        text      — oryginalny tekst newsa (do wykrywania słów kluczowych)
        prices    — słownik z aktualnymi cenami rynkowymi (przekazywany z powrotem
                    w wyniku, używany przez fusion_engine do dalszej analizy)

    Zwraca:
        Słownik z kluczami:
          - impact     : opis wpływu na rynki (np. "DXY ↗️ | XAUUSD ↘️")
          - suggestion : sugestia tradingowa (np. "Szukaj Shorta na Złocie")
          - prices     : przekazany bez zmian słownik cen (dla fusion_engine)
    """
    label = sentiment['label']
    text_lower = text.lower()

    impact = "Neutralny"
    suggestion = "Brak"

    # --- NEWSY O FED I STOPACH PROCENTOWYCH ---
    # FED hawkish (byczy dla dolara) = niedźwiedzi dla złota
    # FED dovish (niedźwiedzi dla dolara) = byczy dla złota
    if "fed" in text_lower or "interest rate" in text_lower:
        if label == "Bullish":
            # Byczy news o stopach = oczekiwania na podwyżki = silniejszy dolar
            impact = "DXY ↗️ | XAUUSD ↘️"
            suggestion = "Szukaj Shorta na Złocie (Silniejszy Dolar)"
        elif label == "Bearish":
            # Niedźwiedzi news o stopach = oczekiwania na cięcia = słabszy dolar
            impact = "DXY ↘️ | XAUUSD ↗️"
            suggestion = "Szukaj Longa na Złocie (Słabszy Dolar)"

    # --- NEWSY BEZPOŚREDNIO O ZŁOCIE ---
    elif "gold" in text_lower or "xau" in text_lower:
        if label == "Bullish":
            # Bezpośredni popyt na złoto (safe haven, zakupy banków centralnych itp.)
            impact = "XAUUSD ↗️"
            suggestion = "Złoto rośnie (Safe Haven / Popyt)"

    return {
        "impact": impact,
        "suggestion": suggestion,
        "prices": prices
    }
