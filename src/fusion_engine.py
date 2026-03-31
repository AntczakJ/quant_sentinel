"""
fusion_engine.py — silnik fuzji sygnałów (sentyment + analiza techniczna).

Odpowiada za:
  - Łączenie sentymentu medialnego (FinBERT) z analizą techniczną wykresu
  - Zastosowanie logiki korelacji makroekonomicznej (DXY/XAU) z logic.py
  - Opcjonalne pogłębienie analizy przez LLM (GPT-4o)
  - Generowanie finalnej decyzji tradingowej z uzasadnieniem

Logika fuzji (Trend Following):
  - Sentyment Byczy + Wykres Byczy  → sygnał LONG
  - Sentyment Niedźwiedzi + Wykres Niedźwiedzi → sygnał SHORT
  - Sprzeczność sentymentu i wykresu → "Czekaj" (brak sygnału)

Uwaga: ten moduł nie jest aktualnie podpięty do main.py.
Przeznaczony do rozbudowy systemu o pełny pipeline news → decyzja.
Aby go użyć, utwórz instancję DecisionEngine(ai_system) i wywołaj evaluate_signal().
"""

from src.logic import interpret_impact


class DecisionEngine:
    """
    Silnik decyzyjny łączący sentyment AI z analizą techniczną.

    Parametry inicjalizacji:
        ai_system — instancja AISystem z sentiment.py (zawiera FinBERT i GPT-4o)
    """

    def __init__(self, ai_system):
        self.ai = ai_system

    def evaluate_signal(self, news: dict, market_data: dict,
                         tech_analysis: dict | None) -> dict | None:
        """
        Przetwarza news przez pełny pipeline i generuje decyzję tradingową.

        Parametry:
            news          — słownik z kluczami 'title' i 'text' (nagłówek i treść newsa)
            market_data   — słownik z kluczem 'live' zawierającym aktualne ceny
            tech_analysis — wynik ChartAnalyzer.analyze_full() lub None jeśli niedostępny

        Etapy przetwarzania:
          1. Szybki sentyment FinBERT — jeśli pewność < 80% → odrzucamy news
          2. Analiza makroekonomiczna (korelacja DXY/XAU) przez logic.py
          3. Pogłębiona analiza LLM przez GPT-4o (opcjonalnie)
          4. Fuzja decyzji — porównanie sentymentu z sygnałem technicznym

        Zwraca:
            Słownik z wynikami analizy i finalną sugestią, lub None jeśli
            sentyment był za słaby (score < 0.80).

        Klucze wyniku:
          - news          : oryginalny news
          - sentiment     : wynik FinBERT (label + score)
          - tech          : wynik analizy technicznej
          - macro_impact  : wynik interpret_impact() z logic.py
          - deep_macro    : interpretacja GPT-4o
          - suggestion    : finalna sugestia (np. "LONG XAUUSD" lub "Obserwuj")
          - alert_needed  : True jeśli należy wysłać alert push na Telegram
        """
        # --- KROK 1: SZYBKI SENTYMENT (FinBERT) ---
        text_to_analyze = f"{news['title']} {news['text']}"
        sentiment = self.ai.fast_sentiment(text_to_analyze)

        # Odrzucamy nieuporządkowane newsy (pewność modelu < 80%)
        if sentiment['score'] < 0.80:
            return None

        # --- KROK 2: LOGIKA MAKROEKONOMICZNA ---
        macro_impact = interpret_impact(sentiment, text_to_analyze, market_data['live'])

        # --- KROK 3: GŁĘBOKA ANALIZA LLM ---
        deep_macro = self.ai.deep_macro_analysis(text_to_analyze, market_data['live'])

        # --- KROK 4: FUZJA DECYZJI ---
        final_suggestion = "Obserwuj"
        alert_needed = False

        # Pobieramy sentyment techniczny z wykresu (lub "Neutral" jeśli brak danych)
        tech_sent = tech_analysis['tech_sentiment'] if tech_analysis else "Neutral"

        if sentiment['label'] == "Bullish" and tech_sent == "Byczy":
            # Pełna konfluencja byków — strongest signal
            final_suggestion = "LONG XAUUSD (Sentyment + Wykres Zgodne)"
            alert_needed = True
        elif sentiment['label'] == "Bearish" and tech_sent == "Niedźwiedzi":
            # Pełna konfluencja niedźwiedzi — strongest signal
            final_suggestion = "SHORT XAUUSD (Sentyment + Wykres Zgodne)"
            alert_needed = True
        elif sentiment['label'] != tech_sent and tech_sent != "Neutral":
            # Sprzeczność — czekamy na klarowniejszy sygnał
            final_suggestion = "Dywergencja (Sentyment sprzeczny z Wykresem) - Czekaj"

        return {
            "news": news,
            "sentiment": sentiment,
            "tech": tech_analysis,
            "macro_impact": macro_impact,
            "deep_macro": deep_macro,
            "suggestion": final_suggestion,
            "alert_needed": alert_needed
        }
