"""
ai_engine.py — integracja z modelami OpenAI (GPT-4o).

Odpowiada za:
  - Interpretację newsów rynkowych (byczy/niedźwiedzi)
  - Analizę sentymentu rynkowego na podstawie danych technicznych
  - Generowanie decyzji tradingowych (TRADE/CZEKAJ) z uwzględnieniem
    historii strat (AI feedback loop)

Wszystkie zapytania są wysyłane do modelu GPT-4o przez oficjalne SDK OpenAI.
Klucz API jest pobierany z config.py (który czyta go z pliku .env).
"""

from openai import OpenAI
from src.config import OPENAI_KEY
from src.logger import logger

# Inicjalizujemy klienta OpenAI raz przy imporcie modułu
if OPENAI_KEY:
    client = OpenAI(api_key=OPENAI_KEY)
    logger.info(f"✅ OpenAI client initialized (key: {OPENAI_KEY[:20]}...)")
else:
    client = None
    logger.warning("⚠️ OpenAI API key not found in .env - AI features will be unavailable")

# Słownik systemowych promptów dla różnych kontekstów analizy.
# Każdy kontekst ma swój specjalistyczny prompt który optymalizuje odpowiedź AI.
# Słownik systemowych promptów - wersja AGRESYWNY TRADER
PROMPTS = {
    "news": (
        "Jesteś rygorystycznym analitykiem GOLD (XAU/USD). "
        "Zinterpretuj newsy pod kątem wpływu na cenę złota. "
        "Format: [BYCZE/NIEDŹWIEDZIE/NEUTRALNE] -> Krótkie uzasadnienie (1 zdanie). "
        "Jeśli news dotyczy silnego dolara, złoto leci w dół."
    ),
    "sentiment": (
        "Jesteś traderem Quant. Twoim kluczowym wskaźnikiem jest korelacja XAU/USD z USD/JPY. "
        "Zasada: Silny wzrost USD/JPY oznacza potężnego Dolara -> SPRZEDAWAJ ZŁOTO. "
        "Jeśli USD/JPY spada, szukaj okazji do KUPNA ZŁOTA. "
        "Na podstawie danych wydaj jasny komunikat: [KIERUNEK] + uzasadnienie korelacji."
    ),
    "analysis": (
        "Jesteś Szefem Analiz w funduszu Hedgingowym. Otrzymujesz newsy z Reuters, Investing i FXStreet. "
        "Twoim zadaniem jest ocenić KONKLUENCJĘ (zgodność):\n"
        "1. Jeśli newsy techniczne (FXStreet) mówią o oporze, a newsy fundamentalne (Reuters) o silnym dolarze -> ZABROŃ KUPNA.\n"
        "2. Szukaj rozbieżności: Jeśli technika mówi BULL, ale newsy krzyczą o jastrzębim FED -> Obniż ocenę do 3/10.\n"
        "Bądź bezlitosny dla słabych setupów."
    ),
    "smc": (
        "Jesteś analitykiem Smart Money Concepts. Oceniasz setup pod kątem:\n"
        "- Liquidity Grab i Market Structure Shift\n"
        "- Order Block i Fair Value Gap\n"
        "- Makro reżim (DXY+VIX)\n"
        "- Formacje DBR/RBD\n"
        "Wydaj werdykt: [WYNIK: X/10], [POWÓD], [RADA]. "
        "Odejmuj punkty za brak konfluencji, dodawaj za zgodność z makro."
    ),
    "trading_signal": (
        "Jesteś ekspertem GOLD (XAU/USD). Uwzględnij siłę dolara przez USD/JPY oraz reżim makro. "
        "Format:\n"
        "🎯 SYGNAŁ: [KUPUJ/SPRZEDAJ/CZEKAJ]\n"
        "💵 DOLAR (USD/JPY): (Opisz czy pcha złoto w dół czy w górę)\n"
        "🌍 MAKRO REŻIM: (Zielony/Czerwony/Neutralny)\n"
        "🛡️ RISK: (Np. 'Wysoki - RSI 75')\n"
        "💡 RADA: (Krótka techniczna wskazówka)."
    )
}


def ask_ai_gold(context_type: str, raw_data: str) -> str:
    """
    Wysyła zapytanie do GPT-4o i zwraca interpretację danych rynkowych.

    Parametry:
        context_type — typ analizy: "news", "sentiment" lub "analysis"
                       Decyduje który prompt systemowy zostanie użyty.
        raw_data     — surowe dane do analizy (tekst z newsami, wartościami
                       wskaźników lub historią strat)

    Zwraca:
        Odpowiedź modelu jako string, lub komunikat błędu jeśli API jest niedostępne.

    Ustawienia modelu:
        - model: gpt-4o (najlepsze rozumienie korelacji rynkowych)
        - temperature: 0.5 (balans między logiką a kreatywnością; niższe = bardziej deterministyczne)
        - max_tokens: domyślnie bez limitu (odpowiedzi są krótkie z natury promptu)
    """
    if not OPENAI_KEY:
        logger.warning("❌ Brak klucza OpenAI - analiza AI niedostępna")
        return "❌ Brak klucza OpenAI - kontaktuj administratora"

    if client is None:
        logger.warning("❌ Klient OpenAI nie został inicjalizowany")
        return "❌ Błąd inicjalizacji OpenAI - spróbuj później"

    # Używamy zdefiniowanego promptu lub generycznego jeśli typ nie jest znany
    system_prompt = PROMPTS.get(context_type, "Analizuj dane rynkowe.")

    try:
        response = client.responses.create(
            model="gpt-4o",
            instructions=system_prompt,
            input=f"DANE RYNKOWE: {raw_data}",
            temperature=0.5  # Niższa temperatura = bardziej logiczne, powtarzalne odpowiedzi
        )
        return response.output_text

    except Exception as e:
        error_msg = f"⚠️ Błąd AI ({type(e).__name__}): {str(e)}"
        logger.error(error_msg)
        return "⚠️ Błąd komunikacji z OpenAI - spróbuj później"
