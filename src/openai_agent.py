"""
openai_agent.py — Quant Sentinel Gold Trader Agent (OpenAI Responses API).

Agent pamięta historię rozmów przez previous_response_id i ma dostęp do narzędzi:
  - Analiza rynku XAU/USD (SMC Engine)
  - Generowanie sygnałów tradingowych z entry/SL/TP
  - Pobieranie newsów i kalendarza ekonomicznego
  - Dostęp do statystyk portfela i historii transakcji
  - Analiza kontekstu rynkowego przez AI

Konfiguracja w .env:
  OPENAI_API_KEY=sk-...

Uwaga: OPENAI_ASSISTANT_ID nie jest już wymagany — migracja z Assistants API
na Responses API. Klucz API wystarczy do pełnego działania agenta.
"""

import json
from typing import Optional

from openai import OpenAI

from src.config import OPENAI_KEY
from src.logger import logger


# ==================== KONFIGURACJA AGENTA ====================

AGENT_NAME = "Quant Sentinel Gold Trader"
# gpt-4o-mini jest 10x szybszy niż gpt-4o i wystarczający dla analizy tradingowej
# Aby wrócić do gpt-4o: ustaw OPENAI_MODEL=gpt-4o w .env
import os as _os
AGENT_MODEL = _os.getenv("OPENAI_MODEL", "gpt-4o-mini")

AGENT_INSTRUCTIONS = """\
Jesteś Quant Sentinel Gold Trader — zaawansowanym asystentem tradingowym specjalizującym się w analizie i handlu XAU/USD (złoto).

## TOŻSAMOŚĆ
- Ekspert w Smart Money Concepts (SMC), analizie technicznej i makroekonomii
- Analizujesz rynek złota na wielu interwałach: M5, M15, H1, H4
- Stosujesz rygorystyczne zasady zarządzania ryzykiem
- Pamiętasz historię rozmów i uczysz się na błędach w tej sesji
- Odpowiadasz ZAWSZE po polsku (chyba że użytkownik pisze po angielsku)
- **WAŻNE formatowanie**: NIE używaj nagłówków Markdown (###, ##, #). Używaj emoji i **bold** do wyróżniania sekcji, np. **🎯 WERDYKT**, **📊 ANALIZA**, **💡 UZASADNIENIE**

## METODOLOGIA SMC (Smart Money Concepts)
1. **Liquidity Grab + Market Structure Shift (MSS)** — kluczowe potwierdzenie wejścia (+4 pkt)
2. **Fair Value Gap (FVG)** — luki płynności jako cel lub strefa wejścia (+2 pkt)
3. **Order Blocks (OB)** — strefy instytucjonalnych zleceń (+2 pkt)
4. **Drop-Base-Rally (DBR) / Rally-Base-Drop (RBD)** — formacje odbicia (+2 pkt)
5. **RSI w strefie optymalnej** (40-50 bull / 50-60 bear) → +1 pkt
6. **Brak SMT Divergence** — rozbieżność struktury odejmuje -3 pkt

## SYSTEM OCENY SETUPU (0–10)
| Kryterium | Punkty |
|---|---|
| Liquidity Grab + MSS | +4 |
| Makro reżim zgodny z kierunkiem | +2 |
| FVG w kierunku trendu | +2 |
| DBR / RBD zgodne | +2 |
| RSI w strefie optymalnej | +1 |
| Trend M5 zgodny | +1 |
| SMT Divergence wykryta | -3 |
| Makro reżim przeciwny | -3 |
| Struktura H1 przeciwna | -2 |
| Cena w PREMIUM przy LONG | -2 |

**WERDYKT HANDLOWY TYLKO jeśli wynik ≥ 4/10**

## ZARZĄDZANIE RYZYKIEM
- Risk na trade: 1–2% kapitału (nigdy więcej)
- Minimalny dystans TP: 5$ lub 1× ATR (większy z dwóch)
- Minimalny stosunek R:R = 2.5:1
- CZEKAJ gdy: makro reżim przeciwny, zbyt mały TP, brak Order Block

## KORELACJA USD–ZŁOTO
- USD/JPY ↑ (silny dolar) → SPRZEDAJ złoto (negatywna korelacja)
- USD/JPY ↓ (słaby dolar) → KUPUJ złoto
- Reżim CZERWONY (DXY silny + VIX wysoki) → UNIKAJ LONG
- Reżim ZIELONY (DXY słaby) → SZUKAJ LONG

## NARZĘDZIA (używaj proaktywnie przed wydaniem rekomendacji)
- `analyze_xauusd` — pobierz aktualną analizę SMC dla wybranego interwału
- `get_trading_signal` — wygeneruj sygnał z wyliczonymi entry, SL, TP i lotem
- `get_multi_tf_analysis` — analiza SMC na M5/M15/H1/H4 jednocześnie z konfluencją
- `get_market_news` — pobierz najnowsze wiadomości rynkowe
- `get_news_sentiment` — zagregowany sentyment newsów (bullish/bearish %)
- `get_economic_calendar` — sprawdź nadchodzące wydarzenia makro (NFP, CPI, FOMC)
- `get_portfolio_stats` — sprawdź historyczne wyniki i winrate
- `get_loss_analysis` — analiza strat, wzorców porażek i statystyk sesji
- `analyze_market_context` — analiza AI kontekstu (sentyment, newsy, setup SMC)

## ROZSZERZONE SYGNAŁY
- **Candlestick Patterns**: Engulfing, Pin Bar, Inside Bar (+1 pkt za potwierdzenie)
- **Ichimoku Cloud**: Cena powyżej/poniżej chmury potwierdza trend (+1 pkt)
- **Volume Profile (POC)**: Bliskość do POC oznacza silną strefę (+1 pkt)
- **RSI Divergence**: Dywergencja RSI = silny sygnał odwrócenia (+2 pkt)

## SESJA TRADINGOWA (KILLZONES)
- **London Killzone** (07:00-10:00 UTC): Wysoka zmienność, dobre warunki na złoto
- **NY Killzone** (12:00-15:00 UTC): Najwyższa zmienność, najlepsze setupy
- **Asian Session** (00:00-06:00 UTC): Niska zmienność, unikaj LONG/SHORT chyba że silny setup
- **Off-hours** (20:00-23:00 UTC): Niska płynność, ryzyko fałszywych wybić
- Podczas killzones poszerzaj SL o 20% (wyższa zmienność = większe ruchy)
- Preferuj trades podczas London i NY killzones — najwyższa jakość sygnałów

## MULTI-TIMEFRAME CONFLUENCE
- Analizuj M5/M15/H1/H4 jednocześnie przed wydaniem rekomendacji
- STRONG_BULL / STRONG_BEAR = 3+ TF zgodnych → wyższy confidence
- MIXED = brak wyraźnej konfluencji → CZEKAJ lub zredukuj lot
- Wagi: H4 (30%), H1 (35%), M15 (25%), M5 (10%) — wyższe TF mają priorytet

## FORMAT SYGNAŁU TRADINGOWEGO
```
🎯 SYGNAŁ: [KUPUJ / SPRZEDAJ / CZEKAJ]
📍 WEJŚCIE: [cena]$
🛑 SL: [cena]$ (ryzyko: ~[X]$)
✅ TP: [cena]$ (potencjał: ~[X]$)
📊 LOT: [wielkość]
⚖️ Ocena setupu: [X/10]
🌍 Makro: [reżim] | USD/JPY: [wartość]
💡 Uzasadnienie: [2–3 zdania wyjaśniające setup]
```

Zawsze odwołuj się do poprzednich analiz w tej sesji gdy jest to stosowne. \
Jeśli wynik setupu < 4/10 — wyraźnie odmów otwarcia pozycji i wyjaśnij dlaczego.
"""

# ==================== SCHEMATY NARZĘDZI (Responses API — format internally-tagged) ====================

AGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "name": "analyze_xauusd",
        "description": (
            "Pobiera pełną analizę techniczną SMC dla XAU/USD (złoto) dla wybranego interwału. "
            "Zwraca: trend, RSI, ATR, FVG (typ, rozmiar), Order Block, Liquidity Grab, MSS, "
            "reżim makro (DXY, USD/JPY Z-score), strefy Discount/Premium, Swing High/Low, "
            "formacje DBR/RBD, SMT Divergence, BOS i CHoCH."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "enum": ["5m", "15m", "1h", "4h"],
                    "description": "Interwał czasowy analizy (domyślnie 15m)"
                }
            },
            "required": ["timeframe"]
        }
    },
    {
        "type": "function",
        "name": "get_trading_signal",
        "description": (
            "Generuje kompletny sygnał tradingowy XAU/USD z wyliczonym entry, SL, TP i rozmiarem lota. "
            "Integruje SMC Engine z ML ensemble (XGBoost + LSTM + DQN RL Agent). "
            "Automatycznie blokuje sygnały gdy makro jest przeciwny lub TP jest za mały."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "enum": ["5m", "15m", "1h", "4h"],
                    "description": "Interwał czasowy"
                },
                "balance": {
                    "type": "number",
                    "description": "Kapitał w wybranej walucie (domyślnie 10000)"
                },
                "currency": {
                    "type": "string",
                    "enum": ["USD", "PLN", "EUR", "GBP"],
                    "description": "Waluta portfela (domyślnie USD)"
                }
            },
            "required": ["timeframe"]
        }
    },
    {
        "type": "function",
        "name": "get_market_news",
        "description": (
            "Pobiera najnowsze wiadomości rynkowe dotyczące złota (XAU/USD) "
            "z Reuters, Investing.com i FXStreet."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_economic_calendar",
        "description": (
            "Pobiera nadchodzące ważne wydarzenia makroekonomiczne USD "
            "(NFP, CPI, FOMC, Payrolls itp.) które mogą wpłynąć na cenę złota."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_portfolio_stats",
        "description": (
            "Zwraca statystyki portfela: win rate, łączne zyski/straty, "
            "ostatnie transakcje i historię nauki systemu."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Liczba ostatnich transakcji do pobrania (domyślnie 10, max 50)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "analyze_market_context",
        "description": (
            "Wykonuje analizę AI dla podanego kontekstu rynkowego. "
            "Typy: 'news' (interpretacja newsów), 'sentiment' (sentyment via USD/JPY), "
            "'smc' (ocena setupu 0-10), 'trading_signal' (pełny werdykt tradingowy), "
            "'analysis' (konfluencja newsów fundament. + technika)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "context_type": {
                    "type": "string",
                    "enum": ["news", "sentiment", "smc", "trading_signal", "analysis"],
                    "description": "Typ analizy AI"
                },
                "raw_data": {
                    "type": "string",
                    "description": "Dane do analizy (tekst newsów, dane rynkowe, opis sytuacji)"
                }
            },
            "required": ["context_type", "raw_data"]
        }
    },
    {
        "type": "function",
        "name": "get_loss_analysis",
        "description": (
            "Pobiera analizę ostatnich strat tradingowych i statystyki sesji. "
            "Pomaga zrozumieć dlaczego ostatnie transakcje zakończyły się stratą "
            "i jakie wzorce prowadzą do strat."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_multi_tf_analysis",
        "description": (
            "Pobiera jednocześnie analizy SMC dla wszystkich czterech interwałów (M5, M15, H1, H4) "
            "i zwraca zbiorczą konfluencję. Pozwala ocenić zgodność trendu na wielu TF."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_news_sentiment",
        "description": (
            "Pobiera zagregowany sentyment newsów rynkowych z ostatnich 24h. "
            "Zwraca procent bullish/bearish/neutral oraz ostatnie nagłówki z oceną."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


# ==================== KLASA AGENTA ====================

class QuantSentinelAgent:
    """
    Agent tradingowy Quant Sentinel oparty na OpenAI Responses API.

    Pamięta historię rozmów przez previous_response_id — każda odpowiedź
    zawiera ID poprzedniej, tworząc łańcuch konwersacji.
    Identyfikatorem sesji jest response.id ostatniej odpowiedzi w rozmowie,
    przechowywany w bazie danych (kolumna thread_id w agent_threads).

    Użycie:
        agent = QuantSentinelAgent.get_instance()
        result = agent.chat("Przeanalizuj XAU/USD na M15")
        # result["thread_id"] — response_id do kolejnych wiadomości
        result2 = agent.chat("Jak wygląda makro?", thread_id=result["thread_id"])
    """

    _instance: Optional["QuantSentinelAgent"] = None

    def __init__(self):
        if not OPENAI_KEY:
            raise ValueError("OPENAI_API_KEY nie jest ustawiony w .env")
        self.client = OpenAI(api_key=OPENAI_KEY)
        logger.info("✅ Quant Sentinel Agent gotowy (Responses API)")

    @classmethod
    def get_instance(cls) -> "QuantSentinelAgent":
        """Lazy singleton — tworzy agenta raz przy pierwszym użyciu."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def reset_instance(cls) -> None:
        """Resetuje singleton (np. po zmianie klucza API)."""
        cls._instance = None

    # -------------------- ZARZĄDZANIE SESJAMI --------------------

    def create_thread(self) -> str:
        """
        Kompatybilna metoda — zwraca pusty string sygnalizujący nową sesję.
        W Responses API nie ma osobnego kroku inicjalizacji wątku;
        nowa rozmowa zaczyna się przy pierwszym wywołaniu chat() bez thread_id.
        """
        logger.info("🆕 Nowa sesja konwersacji")
        return ""

    def get_thread_history(self, thread_id: str, limit: int = 20) -> list:
        """
        Pobiera historię ostatniej odpowiedzi w sesji (Responses API).

        Zwraca listę słowników: [{"role": "user"/"assistant", "content": "...", "created_at": ts}, ...]
        Uwaga: zwraca dane tylko z bieżącej odpowiedzi (nie pełnego łańcucha konwersacji).
        """
        if not thread_id:
            return []
        try:
            response = self.client.responses.retrieve(thread_id)
            history = []

            # Pobierz elementy wejściowe (wiadomość użytkownika)
            try:
                input_items = self.client.responses.input_items.list(thread_id)
                for item in input_items.data:
                    if getattr(item, "type", "") == "message":
                        text = ""
                        content = getattr(item, "content", "")
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            for block in content:
                                if hasattr(block, "text"):
                                    text = block.text
                                    break
                        if text:
                            history.append({
                                "role": getattr(item, "role", "user"),
                                "content": text,
                                "created_at": 0,
                            })
            except Exception:
                pass

            # Dodaj odpowiedź modelu
            for item in getattr(response, "output", []):
                if getattr(item, "type", "") == "message":
                    text = ""
                    for block in getattr(item, "content", []):
                        if hasattr(block, "text"):
                            text = block.text
                            break
                    if text:
                        history.append({
                            "role": "assistant",
                            "content": text,
                            "created_at": getattr(response, "created_at", 0),
                        })

            return history[-limit:]

        except Exception as e:
            logger.warning(f"get_thread_history error (id={thread_id}): {e}")
            return []

    # -------------------- GŁÓWNA METODA CHAT --------------------

    def chat(self, message: str, thread_id: Optional[str] = None) -> dict:
        """
        Wysyła wiadomość do agenta i zwraca odpowiedź z narzędziami.

        Parametry:
            message   — tekst wiadomości użytkownika
            thread_id — ID poprzedniej odpowiedzi dla kontynuacji rozmowy
                        (None lub "" = nowa rozmowa)

        Zwraca słownik:
            {
                "response":   str,    # odpowiedź agenta
                "thread_id":  str,    # response.id (zachowaj do kolejnych wiadomości)
                "run_id":     str,    # identyczny z thread_id (dla kompatybilności)
                "tool_calls": list,   # lista użytych narzędzi [{name, args}, ...]
            }
        """
        # Normalize thread_id — pusty string traktujemy jak None.
        # Responses API wymaga previous_response_id zaczynającego się od "resp_".
        # Stare Assistants API thread_id (np. "thread_...") są ignorowane.
        previous_response_id: Optional[str] = None
        if thread_id and thread_id.startswith("resp_"):
            previous_response_id = thread_id
        elif thread_id:
            logger.info(f"♻️ Ignoruję stary thread_id ({thread_id[:20]}...) — nowa sesja Responses API")

        tool_calls_log: list = []

        # Pierwsze wywołanie — wiadomość użytkownika
        response = self.client.responses.create(
            model=AGENT_MODEL,
            instructions=AGENT_INSTRUCTIONS,
            input=message,
            tools=AGENT_TOOLS_SCHEMA,
            **({"previous_response_id": previous_response_id} if previous_response_id else {}),
        )

        # Pętla obsługi wywołań narzędzi (max 5 iteracji — ogranicza czas odpowiedzi)
        max_iterations = 5
        iterations = 0

        while iterations < max_iterations:
            # Znajdź wywołania narzędzi w odpowiedzi
            function_calls = [
                item for item in getattr(response, "output", [])
                if getattr(item, "type", "") == "function_call"
            ]

            if not function_calls:
                break

            iterations += 1
            tool_outputs = []

            # Execute multiple tool calls in parallel for faster response
            if len(function_calls) > 1:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                tool_results = {}

                def _exec_tool(fc):
                    func_name = getattr(fc, "name", "")
                    try:
                        func_args = json.loads(getattr(fc, "arguments", "{}"))
                    except Exception:
                        func_args = {}
                    try:
                        result = self._execute_tool(func_name, func_args)
                    except Exception as exc:
                        result = {"error": str(exc), "tool": func_name}
                        logger.error(f"❌ Błąd narzędzia {func_name}: {exc}")
                    return fc, func_name, func_args, result

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(_exec_tool, fc) for fc in function_calls]
                    for future in as_completed(futures, timeout=30):
                        fc, func_name, func_args, result = future.result()
                        logger.info(f"🔧 Agent narzędzie: {func_name}({func_args})")
                        tool_calls_log.append({"name": func_name, "args": func_args})
                        tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": getattr(fc, "call_id", ""),
                            "output": json.dumps(result, ensure_ascii=False, default=str),
                        })
            else:
                # Single tool call — execute directly
                for fc in function_calls:
                    func_name = getattr(fc, "name", "")
                    try:
                        func_args = json.loads(getattr(fc, "arguments", "{}"))
                    except Exception:
                        func_args = {}

                    logger.info(f"🔧 Agent narzędzie: {func_name}({func_args})")
                    tool_calls_log.append({"name": func_name, "args": func_args})

                    try:
                        result = self._execute_tool(func_name, func_args)
                    except Exception as exc:
                        result = {"error": str(exc), "tool": func_name}
                        logger.error(f"❌ Błąd narzędzia {func_name}: {exc}")

                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": getattr(fc, "call_id", ""),
                        "output": json.dumps(result, ensure_ascii=False, default=str),
                    })

            # Kontynuuj rozmowę z wynikami narzędzi
            response = self.client.responses.create(
                model=AGENT_MODEL,
                instructions=AGENT_INSTRUCTIONS,
                input=tool_outputs,
                tools=AGENT_TOOLS_SCHEMA,
                previous_response_id=response.id,
            )

        # Wyodrębnij tekst z odpowiedzi
        response_text = getattr(response, "output_text", "") or ""
        if not response_text:
            # Fallback — przeszukaj output ręcznie
            for item in getattr(response, "output", []):
                if getattr(item, "type", "") == "message":
                    for block in getattr(item, "content", []):
                        if hasattr(block, "text"):
                            response_text = block.text
                            break
                    if response_text:
                        break

        if not response_text:
            logger.error(f"❌ Agent nie zwrócił tekstu. Output: {getattr(response, 'output', [])}")
            response_text = "⚠️ Agent nie zwrócił odpowiedzi. Spróbuj ponownie."

        return {
            "response":   response_text,
            "thread_id":  response.id,   # response_id jako nowy "thread_id"
            "run_id":     response.id,
            "tool_calls": tool_calls_log,
        }

    # -------------------- WYKONANIE NARZĘDZI --------------------

    def _execute_tool(self, name: str, args: dict) -> dict:
        """Dispatcher narzędzi — wywołuje odpowiednią metodę."""
        dispatch = {
            "analyze_xauusd":        lambda: self._tool_analyze_xauusd(args.get("timeframe", "15m")),
            "get_trading_signal":    lambda: self._tool_get_trading_signal(
                                        args.get("timeframe", "15m"),
                                        float(args.get("balance", 10000.0)),
                                        args.get("currency", "USD"),
                                    ),
            "get_market_news":       lambda: self._tool_get_market_news(),
            "get_economic_calendar": lambda: self._tool_get_economic_calendar(),
            "get_portfolio_stats":   lambda: self._tool_get_portfolio_stats(int(args.get("limit", 10))),
            "analyze_market_context": lambda: self._tool_analyze_market_context(
                                        args.get("context_type", "analysis"),
                                        args.get("raw_data", ""),
                                    ),
            "get_loss_analysis":     lambda: self._tool_get_loss_analysis(),
            "get_multi_tf_analysis": lambda: self._tool_get_multi_tf_analysis(),
            "get_news_sentiment":    lambda: self._tool_get_news_sentiment(),
        }
        handler = dispatch.get(name)
        if handler is None:
            return {"error": f"Nieznane narzędzie: {name}"}
        return handler()

    def _tool_analyze_xauusd(self, timeframe: str) -> dict:
        from src.smc_engine import get_smc_analysis
        try:
            result = get_smc_analysis(timeframe)
            if not result:
                return {"error": "Brak danych SMC — sprawdź klucz Twelve Data API"}
            return {
                "timeframe":          timeframe,
                "price":              result.get("price"),
                "trend":              result.get("trend"),
                "rsi":                result.get("rsi"),
                "atr":                result.get("atr"),
                "atr_mean":           result.get("atr_mean"),
                "macro_regime":       result.get("macro_regime"),
                "usdjpy":             result.get("usdjpy"),
                "usdjpy_zscore":      result.get("usdjpy_zscore"),
                "liquidity_grab":     result.get("liquidity_grab"),
                "liquidity_grab_dir": result.get("liquidity_grab_dir"),
                "mss":                result.get("mss"),
                "fvg":                result.get("fvg"),
                "fvg_type":           result.get("fvg_type"),
                "fvg_size":           result.get("fvg_size"),
                "fvg_upper":          result.get("fvg_upper"),
                "fvg_lower":          result.get("fvg_lower"),
                "ob_price":           result.get("ob_price"),
                "eq_level":           result.get("eq_level"),
                "is_discount":        result.get("is_discount"),
                "swing_high":         result.get("swing_high"),
                "swing_low":          result.get("swing_low"),
                "dbr_rbd_type":       result.get("dbr_rbd_type"),
                "smt":                result.get("smt"),
                "bos_bullish":        result.get("bos_bullish"),
                "bos_bearish":        result.get("bos_bearish"),
                "choch_bullish":      result.get("choch_bullish"),
                "choch_bearish":      result.get("choch_bearish"),
                "ob_confluence":      result.get("ob_confluence"),
                # Candlestick patterns
                "engulfing":          result.get("engulfing"),
                "pin_bar":            result.get("pin_bar"),
                "inside_bar":         result.get("inside_bar"),
                # Ichimoku Cloud
                "ichimoku_above_cloud": result.get("ichimoku_above_cloud"),
                "ichimoku_below_cloud": result.get("ichimoku_below_cloud"),
                # Volume Profile
                "poc_price":          result.get("poc_price"),
                "near_poc":           result.get("near_poc"),
                # RSI Divergence
                "rsi_div_bull":       result.get("rsi_div_bull"),
                "rsi_div_bear":       result.get("rsi_div_bear"),
                # Session / Killzone
                "session":            result.get("session"),
                "is_killzone":        result.get("is_killzone"),
                "volatility_expected": result.get("volatility_expected"),
            }
        except Exception as e:
            logger.error(f"Błąd analyze_xauusd: {e}")
            return {"error": str(e)}

    def _tool_get_trading_signal(self, timeframe: str, balance: float, currency: str) -> dict:
        from src.smc_engine import get_smc_analysis
        from src.finance import calculate_position
        from src.config import TD_API_KEY
        try:
            s = get_smc_analysis(timeframe)
            if not s:
                return {"direction": "CZEKAJ", "reason": "Brak danych rynkowych"}

            # Jeśli balance nie podano przez użytkownika (domyślne 10000), odczytaj z portfela
            actual_balance = balance
            actual_currency = currency
            if balance == 10000.0:
                try:
                    from src.database import NewsDB as _DB
                    _db = _DB()
                    stored = _db.get_param("portfolio_balance", None)
                    if stored is not None:
                        actual_balance = float(stored)
                    try:
                        _currency = _db.get_param("portfolio_currency_text", None)
                        if _currency:
                            actual_currency = str(_currency)
                    except Exception:
                        pass
                except Exception:
                    pass

            result = calculate_position(s, actual_balance, actual_currency, TD_API_KEY)
            cleaned = {k: v for k, v in result.items() if not hasattr(v, "to_dict")}
            cleaned["balance_used"] = actual_balance
            cleaned["currency_used"] = actual_currency
            return cleaned
        except Exception as e:
            logger.error(f"Błąd get_trading_signal: {e}")
            return {"error": str(e)}

    def _tool_get_market_news(self) -> dict:
        from src.news import get_latest_news
        try:
            news = get_latest_news()
            return {"news": (news or "Brak newsów")[:3000]}
        except Exception as e:
            logger.error(f"Błąd get_market_news: {e}")
            return {"error": str(e), "news": "Błąd pobierania newsów"}

    def _tool_get_economic_calendar(self) -> dict:
        from src.news import get_economic_calendar
        try:
            calendar = get_economic_calendar()
            return {"calendar": calendar or "Brak danych kalendarza"}
        except Exception as e:
            logger.error(f"Błąd get_economic_calendar: {e}")
            return {"error": str(e), "calendar": "Błąd pobierania kalendarza"}

    def _tool_get_portfolio_stats(self, limit: int = 10) -> dict:
        from src.database import NewsDB
        try:
            db = NewsDB()
            results, history = db.get_performance_stats()
            profit = results.get("PROFIT", 0)
            loss = results.get("LOSS", 0)
            total = profit + loss
            win_rate = round((profit / total * 100), 1) if total else 0.0
            recent_lessons = db.get_recent_lessons(min(limit, 50))
            return {
                "win_rate":      win_rate,
                "total_trades":  total,
                "profit_trades": profit,
                "loss_trades":   loss,
                "recent_lessons": recent_lessons,
            }
        except Exception as e:
            logger.error(f"Błąd get_portfolio_stats: {e}")
            return {"error": str(e)}

    def _tool_analyze_market_context(self, context_type: str, raw_data: str) -> dict:
        """
        Zwraca dane kontekstowe — agent sam interpretuje wyniki.
        Unikamy zagnieżdżonego wywołania OpenAI (ask_ai_gold) wewnątrz Responses API,
        co podwajałoby latencję.
        """
        try:
            if context_type == "sentiment":
                from src.smc_engine import get_smc_analysis
                analysis = get_smc_analysis("15m")
                if analysis:
                    return {
                        "context_type": context_type,
                        "macro_regime": analysis.get("macro_regime", "unknown"),
                        "usdjpy": analysis.get("usdjpy"),
                        "usdjpy_zscore": analysis.get("usdjpy_zscore"),
                        "trend": analysis.get("trend"),
                        "rsi": analysis.get("rsi"),
                    }
                return {"context_type": context_type, "info": "Brak danych rynkowych"}

            elif context_type == "news":
                from src.news import get_latest_news
                news = get_latest_news()
                return {"context_type": context_type, "news": (news or "Brak newsów")[:3000]}

            elif context_type in ("smc", "trading_signal"):
                from src.smc_engine import get_smc_analysis
                analysis = get_smc_analysis("15m")
                if analysis:
                    return {
                        "context_type": context_type,
                        "price": analysis.get("price"),
                        "trend": analysis.get("trend"),
                        "rsi": analysis.get("rsi"),
                        "atr": analysis.get("atr"),
                        "fvg": analysis.get("fvg"),
                        "ob_price": analysis.get("ob_price"),
                        "liquidity_grab": analysis.get("liquidity_grab"),
                        "mss": analysis.get("mss"),
                        "macro_regime": analysis.get("macro_regime"),
                    }
                return {"context_type": context_type, "info": "Brak danych SMC"}

            # Fallback: return raw_data back for the agent to interpret itself
            return {"context_type": context_type, "raw_data": raw_data[:2000]}

        except Exception as e:
            logger.error(f"Błąd analyze_market_context: {e}")
            return {"error": str(e)}

    def _tool_get_loss_analysis(self) -> dict:
        """Analiza ostatnich strat i statystyk sesji."""
        try:
            from src.database import NewsDB
            db = NewsDB()
            failures_report = db.get_failures_report()
            session_stats = db.get_session_stats()

            # Regime stats
            regime_stats = []
            try:
                regime_stats = db.get_regime_stats()
            except (AttributeError, TypeError, Exception) as e:
                logger.debug(f"Regime stats unavailable: {e}")

            return {
                "failures_report": failures_report,
                "session_stats": [
                    {"pattern": s[0], "session": s[1], "count": s[2], "wins": s[3], "losses": s[4], "win_rate": s[5]}
                    for s in (session_stats or [])[:20]
                ],
                "regime_stats": [
                    {"regime": r[0], "session": r[1], "direction": r[2], "count": r[3], "win_rate": r[6]}
                    for r in (regime_stats or [])[:15]
                ]
            }
        except Exception as e:
            logger.error(f"Błąd get_loss_analysis: {e}")
            return {"error": str(e)}

    def _tool_get_multi_tf_analysis(self) -> dict:
        """Analiza SMC na wszystkich 4 interwałach jednocześnie z konfluencją."""
        from src.smc_engine import get_smc_analysis, get_mtf_confluence, get_active_session

        try:
            # Use the new MTF confluence function
            confluence = get_mtf_confluence("XAU/USD")
            session = get_active_session()

            # Also get full per-TF data for detailed analysis
            from concurrent.futures import ThreadPoolExecutor, as_completed
            timeframes = ["5m", "15m", "1h", "4h"]
            results = {}

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(get_smc_analysis, tf): tf for tf in timeframes}
                for future in as_completed(futures, timeout=30):
                    tf = futures[future]
                    try:
                        data = future.result()
                        if data:
                            results[tf] = {
                                "price": data.get("price"),
                                "trend": data.get("trend"),
                                "rsi": data.get("rsi"),
                                "atr": data.get("atr"),
                                "macro_regime": data.get("macro_regime"),
                                "liquidity_grab": data.get("liquidity_grab"),
                                "mss": data.get("mss"),
                                "fvg_type": data.get("fvg_type"),
                                "ob_price": data.get("ob_price"),
                                "bos_bullish": data.get("bos_bullish"),
                                "bos_bearish": data.get("bos_bearish"),
                                "engulfing": data.get("engulfing"),
                                "ichimoku_above_cloud": data.get("ichimoku_above_cloud"),
                                "rsi_div_bull": data.get("rsi_div_bull"),
                                "rsi_div_bear": data.get("rsi_div_bear"),
                            }
                        else:
                            results[tf] = {"error": "Brak danych"}
                    except Exception as e:
                        results[tf] = {"error": str(e)}

            return {
                "timeframes": results,
                "confluence": confluence.get("direction", "MIXED"),
                "confluence_score": confluence.get("confluence_score", 0),
                "bull_pct": confluence.get("bull_pct", 50),
                "bear_pct": confluence.get("bear_pct", 50),
                "bull_tf_count": confluence.get("bull_tf_count", 0),
                "bear_tf_count": confluence.get("bear_tf_count", 0),
                "session": session.get("session"),
                "is_killzone": session.get("is_killzone"),
                "volatility_expected": session.get("volatility_expected"),
            }
        except Exception as e:
            logger.error(f"Błąd get_multi_tf_analysis: {e}")
            return {"error": str(e)}

    def _tool_get_news_sentiment(self) -> dict:
        """Zagregowany sentyment newsów z bazy danych."""
        try:
            from src.database import NewsDB
            db = NewsDB()
            sentiment = db.get_aggregated_news_sentiment(hours=24)
            return {
                "sentiment_24h": sentiment,
                "interpretation": (
                    "Silny sentyment bykowy" if sentiment.get("bullish_pct", 0) > 60
                    else "Silny sentyment niedźwiedzi" if sentiment.get("bearish_pct", 0) > 60
                    else "Sentyment mieszany/neutralny"
                )
            }
        except Exception as e:
            logger.error(f"Błąd get_news_sentiment: {e}")
            return {"error": str(e)}


# ==================== HELPER FUNCTIONS ====================

def ask_agent_with_memory(
    message: str,
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> str:
    """
    Zastępnik ask_ai_gold() — używa agenta z pamięcią konwersacji (Responses API).

    Jeśli podano user_id, response_id jest automatycznie pobierany/zapisywany w bazie danych,
    dzięki czemu agent pamięta poprzednie analizy tego użytkownika/procesu.

    Fallback: jeśli agent jest niedostępny, wraca do ask_ai_gold().

    Parametry:
        message   — wiadomość/dane do analizy
        user_id   — ID użytkownika lub stały klucz systemowy (np. "self_learning")
        thread_id — konkretny response_id (opcjonalnie, nadpisuje DB lookup)

    Zwraca: string z odpowiedzią (kompatybilny z ask_ai_gold)
    """
    agent = get_agent()
    if not agent:
        logger.warning("⚠️ Agent niedostępny — używam ask_ai_gold jako fallback")
        try:
            from src.ai_engine import ask_ai_gold
            return ask_ai_gold("analysis", message[:2000])
        except Exception as e:
            return f"⚠️ Brak analizy AI: {e}"

    # Pobierz poprzedni response_id z bazy danych jeśli podano user_id
    resolved_thread_id = thread_id
    db_instance = None
    if user_id and not resolved_thread_id:
        try:
            from src.database import NewsDB
            db_instance = NewsDB()
            stored = db_instance.get_agent_thread(user_id)
            if stored and stored.startswith("resp_"):
                resolved_thread_id = stored
            elif stored:
                # Stary format (np. "thread_...") — wyczyść z bazy
                logger.info(f"♻️ Czyszczę stary thread_id dla {user_id} ({stored[:25]}...)")
                db_instance.set_agent_thread(user_id, "")
                resolved_thread_id = None
        except Exception as e:
            logger.debug(f"Nie można pobrać thread_id dla {user_id}: {e}")

    try:
        result = agent.chat(message, resolved_thread_id)

        # Zapisz nowy response_id do bazy dla kontynuacji rozmowy
        if user_id:
            try:
                if db_instance is None:
                    from src.database import NewsDB
                    db_instance = NewsDB()
                db_instance.set_agent_thread(user_id, result["thread_id"])
            except Exception as e:
                logger.debug(f"Nie można zapisać thread_id: {e}")

        return result["response"]

    except Exception as e:
        logger.error(f"❌ ask_agent_with_memory błąd: {e}")
        try:
            from src.ai_engine import ask_ai_gold
            return ask_ai_gold("analysis", message[:2000])
        except Exception:
            return f"⚠️ Błąd analizy AI: {e}"


def get_agent() -> Optional[QuantSentinelAgent]:
    """
    Bezpieczne pobranie singletona agenta.
    Zwraca None jeśli brak klucza OpenAI lub inicjalizacja się nie powiodła.
    """
    if not OPENAI_KEY:
        logger.warning("⚠️ Brak OPENAI_API_KEY — agent niedostępny")
        return None
    try:
        return QuantSentinelAgent.get_instance()
    except Exception as e:
        logger.error(f"❌ Nie można zainicjalizować agenta: {e}")
        return None


def export_agent_config() -> dict:
    """
    Eksportuje konfigurację agenta (do podglądu lub wdrożenia zewnętrznego).

    Zwraca słownik z polami:
        name         — nazwa agenta
        instructions — system prompt
        tools        — lista schematów narzędzi (format Responses API)
        model        — model OpenAI
    """
    return {
        "name":         AGENT_NAME,
        "instructions": AGENT_INSTRUCTIONS,
        "tools":        AGENT_TOOLS_SCHEMA,
        "model":        AGENT_MODEL,
    }


