"""
sentiment.py — lokalna analiza sentymentu za pomocą modelu FinBERT.

Odpowiada za:
  - Szybką klasyfikację nastrojów rynkowych (Bullish/Bearish/Neutral)
    przy użyciu modelu FinBERT (ProsusAI/finbert) działającego lokalnie
  - Głębszą interpretację tekstu przez GPT-4o (via OpenAI API)
  - Udostępnienie funkcji get_sentiment_data() wywoływanej przez main.py

Naprawione błędy:
  - Zmieniono inicjalizację modelu z poziomu modułu na lazy loading
    (poprzednio AISystem() był tworzony przy każdym imporcie modułu,
    ładując ~500MB modelu FinBERT do RAM nawet gdy nie był potrzebny)
  - Model jest teraz ładowany tylko przy pierwszym wywołaniu get_sentiment_data()

Uwaga: pierwsze wywołanie może potrwać kilkanaście sekund (pobieranie modelu).
"""

import os
import torch
from scipy.special import softmax
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from openai import OpenAI

from src.cache import cached
from src.logger import logger


class AISystem:
    """
    System dwuetapowej analizy sentymentu:
      1. Szybka klasyfikacja lokalna (FinBERT) — bez opóźnień sieciowych
      2. Głęboka interpretacja przez GPT-4o (wymaga API key i połączenia)
    """

    def __init__(self):
        logger.info("⏳ Ładowanie modelu FinBERT... (może potrwać kilkanaście sekund)")

        # Pobiera i ładuje tokenizer i model FinBERT z HuggingFace Hub
        # Model jest zapisywany w cache lokalnie po pierwszym pobraniu
        self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")

        # Klucz OpenAI pobierany z .env przez zmienne środowiskowe
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        logger.info("✅ FinBERT załadowany.")

    def get_fast_sentiment(self, text: str) -> str:
        """
        Klasyfikuje sentyment tekstu za pomocą lokalnego modelu FinBERT.

        Parametry:
            text — tekst do klasyfikacji (nagłówek newsa, opis sytuacji rynkowej)

        Zwraca:
            "Bullish", "Bearish" lub "Neutral" — etykieta z najwyższym prawdopodobieństwem.

        FinBERT zwraca 3 logity (pozytywny/negatywny/neutralny).
        Softmax przekształca je na prawdopodobieństwa, wybieramy argmax.
        """
        inputs = self.tokenizer(
            text, padding=True, truncation=True, return_tensors="pt"
        )
        with torch.no_grad():  # Wyłączamy gradienty — nie trenujemy, tylko inferujemy
            outputs = self.model(**inputs)

        # Konwertujemy logity na prawdopodobieństwa przez softmax
        scores = softmax(outputs.logits.numpy().squeeze())

        # Mapowanie indeksów FinBERT na etykiety (kolejność: positive, negative, neutral)
        label_map = {0: "Bullish", 1: "Bearish", 2: "Neutral"}
        return label_map[scores.argmax()]

    def get_deep_explanation(self, text: str) -> str:
        """
        Generuje krótkie wyjaśnienie newsa przez GPT-4o.

        Parametry:
            text — tekst newsa do interpretacji

        Zwraca:
            Jedno zdanie wyjaśnienia w kontekście rynku złota,
            lub komunikat błędu jeśli API jest niedostępne.
        """
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Mini wystarczy do prostych interpretacji
                messages=[
                    {
                        "role": "system",
                        "content": "Jesteś ekspertem złota. Wyjaśnij news w 1 krótkim zdaniu."
                    },
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content
        except Exception:
            return "Błąd połączenia z OpenAI."


# --- LAZY LOADING ---
# Instancja jest tworzona tylko przy pierwszym wywołaniu get_sentiment_data(),
# a nie przy każdym imporcie modułu. Oszczędza ~500MB RAM i czas startu.
_ai_instance: AISystem | None = None


def _get_ai_instance() -> AISystem:
    """Zwraca instancję AISystem, tworząc ją przy pierwszym wywołaniu."""
    global _ai_instance
    if _ai_instance is None:
        _ai_instance = AISystem()
    return _ai_instance

@cached('sentiment', ttl=180)
def get_sentiment_data(text_to_analyze: str = None) -> str:
    """
    Główna funkcja wywoływana przez main.py po kliknięciu przycisku "SENTYMENT AI".

    Wykonuje dwuetapową analizę:
      1. Klasyfikacja lokalna przez FinBERT (szybka, offline)
      2. Głęboka interpretacja przez GPT-4o (wolniejsza, wymaga API)

    Zwraca:
        Sformatowany string z wynikami obu analiz gotowy do wysłania na Telegram.

    Uwaga: tekst testowy jest przykładowy — w produkcji można tu podpiąć
    scraping newsów z news.py lub data_collector.py.
    """
    try:
        ai = _get_ai_instance()

        # Jeśli nie przekazaliśmy tekstu, używamy domyślnego (lepiej tu podpiąć newsy)
        if not text_to_analyze:
            text_to_analyze = (
                "Gold prices are consolidating as investors await FED inflation data "
                "and DXY remains stable."
            )

        # Krok 1: szybka klasyfikacja lokalna
        fast = ai.get_fast_sentiment(text_to_analyze)

        # Krok 2: głęboka analiza
        deep = ai.get_deep_explanation(text_to_analyze)

        return f"Wiadomość: {text_to_analyze}\n📊 FinBERT: {fast}\n🧠 Analiza: {deep}"

    except Exception as e:
        return f"⚠️ Błąd analizy sentymentu: {e}"