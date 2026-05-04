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
from src.core.config import OPENAI_KEY
from src.core.logger import logger

# Inicjalizujemy klienta OpenAI raz przy imporcie modułu
if OPENAI_KEY:
    client = OpenAI(api_key=OPENAI_KEY)
    # 2026-05-04 fix: don't log key prefix even partially (security audit
    # flagged 20-char prefix as sufficient for reconnaissance attacks).
    logger.info("OpenAI client initialized (key configured)")
else:
    client = None
    logger.warning("⚠️ OpenAI API key not found in .env - AI features will be unavailable")


# 2026-05-04: token usage tracking. Per-call adds to daily counter in
# dynamic_params. Daily reset implicit via date-keyed param.
# Pricing reference (gpt-4o): $2.50/1M input, $10/1M output.
_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def _record_openai_usage(input_tokens: int, output_tokens: int, model: str = "gpt-4o") -> None:
    """Append today's input/output tokens + estimated $ to dynamic_params."""
    try:
        from datetime import date
        from src.core.database import NewsDB
        db = NewsDB()
        today = date.today().isoformat()
        in_key = f"openai_tokens_in_{today}"
        out_key = f"openai_tokens_out_{today}"
        cost_key = f"openai_cost_usd_{today}"
        prev_in = float(db.get_param(in_key, 0) or 0)
        prev_out = float(db.get_param(out_key, 0) or 0)
        prev_cost = float(db.get_param(cost_key, 0) or 0)
        # $ per token
        pricing = _PRICING.get(model, _PRICING["gpt-4o"])
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        db.set_param(in_key, prev_in + input_tokens)
        db.set_param(out_key, prev_out + output_tokens)
        db.set_param(cost_key, round(prev_cost + cost, 4))
    except Exception as e:
        logger.debug(f"openai usage recording failed: {e}")

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

    # 2026-05-04: retry with exponential backoff on transient errors
    # (429 rate limit, 500/502/503 service errors). Max 3 attempts,
    # backoff 1s → 2s → 4s. Per 6-agent integration audit.
    import time as _time
    max_attempts = 3
    last_err = None
    for attempt in range(max_attempts):
        try:
            response = client.responses.create(
                model="gpt-4o",
                instructions=system_prompt,
                input=f"DANE RYNKOWE: {raw_data}",
                temperature=0.5,
            )
            # 2026-05-04: log token usage for daily $ budget tracking.
            # gpt-4o pricing ~$2.50/1M input + $10/1M output. Sum
            # daily via dynamic_params openai_tokens_today_in/out.
            try:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    in_t = int(getattr(usage, "input_tokens", 0) or 0)
                    out_t = int(getattr(usage, "output_tokens", 0) or 0)
                    _record_openai_usage(in_t, out_t, model="gpt-4o")
            except Exception:
                pass
            return response.output_text
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            # Retry only on transient errors
            transient = (
                "429" in err_str or "rate" in err_str
                or "500" in err_str or "502" in err_str or "503" in err_str
                or "timeout" in err_str or "connection" in err_str
            )
            if not transient or attempt == max_attempts - 1:
                logger.error(f"OpenAI call failed (final, {type(e).__name__}): {e}")
                return "⚠️ Błąd komunikacji z OpenAI - spróbuj później"
            backoff = 2 ** attempt
            logger.warning(f"OpenAI transient error (attempt {attempt+1}/{max_attempts}): "
                           f"{type(e).__name__}; retrying in {backoff}s")
            _time.sleep(backoff)
    # Shouldn't reach here, but defensive
    return "⚠️ Błąd komunikacji z OpenAI - spróbuj później"
