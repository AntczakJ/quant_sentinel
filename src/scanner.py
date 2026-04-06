"""
scanner.py — autonomiczny skaner rynku i resolver transakcji.

Multi-Timeframe Cascade:
  - scan_market_task przeszukuje timeframe'y od najwyższego do najniższego:
    4h → 1h → 15m → 5m
  - Jeśli na danym TF znajdzie ważny setup, stawia trade i przerywa kaskadę.
  - Jeśli żaden TF nie daje sygnału, loguje heartbeat.

Naprawiono:
  - scan_market_task teraz zapisuje sygnały do scanner_signals
  - resolve_trades_task zapisuje powód i okoliczności przegranej do trades
  - processed_news jest teraz wypełniana przy alertach FVG/trend
"""

import hashlib
import requests
import time as _time

from src.logger import logger
from src.config import TOKEN, CHAT_ID, USER_PREFS, LAST_STATUS, LAST_STATUS_LOCK, TD_API_KEY
from src.smc_engine import get_smc_analysis

# Kolejność kaskady: od najwyższego do najniższego timeframe'u
SCAN_TIMEFRAMES = ["4h", "1h", "15m", "5m"]

TF_LABELS = {
    "4h": "H4",
    "1h": "H1",
    "15m": "M15",
    "5m": "M5",
}

def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def send_telegram_alert(text: str):
    """
    Pomocnicza funkcja do wysyłania powiadomień push na Telegram.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logger.error(f"❌ Błąd wysyłki Telegram: {e}")


# =============================================================================
# MULTI-TIMEFRAME TRADE EVALUATOR
# =============================================================================

def _evaluate_tf_for_trade(tf: str, db, balance: float = 10000, currency: str = "USD") -> dict | None:
    """
    Ocenia dany timeframe pod kątem ważnego setupu tradingowego.

    Zwraca dict z parametrami trade'a jeśli setup jest ważny, None jeśli nie.

    Walidacja obejmuje:
      0. Price sanity check (porównanie z persistent cache)
      1. Analiza SMC (trend, FVG, liquidity grab, MSS, order blocks)
      2. Filtr fail-rate wzorca (>75% → skip)
      3. Filtr wagi wzorca z self-learning (<0.5 → skip)
      4. Obliczenie pozycji (SL/TP) przez calculate_position
      5. Sprawdzenie kierunku (CZEKAJ → skip)
      6. ML ensemble validation (niska pewność → ostrzeżenie, ale nie blokuje)
    """
    from src.finance import calculate_position
    from src.self_learning import get_pattern_adjustment

    analysis = get_smc_analysis(tf)
    if not analysis:
        logger.debug(f"🔍 [MTF] {tf}: brak danych SMC — pomijam")
        return None

    current_price = analysis['price']
    current_rsi = analysis['rsi']
    current_trend = analysis['trend']

    # --- 0. PRICE SANITY CHECK ---
    if current_price <= 0:
        logger.debug(f"🔍 [MTF] {tf}: cena <= 0 — pomijam")
        return None
    try:
        from api.routers.market import _persistent_cache as _mkt_pc
        ref = float(_mkt_pc.get("ticker", {}).get("price", 0))
        if ref > 1000:
            deviation = abs(current_price - ref) / ref
            if deviation > 0.20:
                logger.warning(
                    f"🔍 [MTF] {tf}: Price sanity FAIL: SMC=${current_price:.2f} vs "
                    f"ticker=${ref:.2f} (Δ{deviation:.0%}) — pomijam"
                )
                return None
    except Exception:
        pass  # persistent_cache not available outside FastAPI context
    current_structure = analysis.get('structure', 'Stable')
    current_fvg = analysis.get('fvg')
    current_fvg_type = analysis.get('fvg_type')

    # --- 1. FILTR FAIL RATE ---
    fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)
    if fail_rate > 75:
        logger.info(f"🔍 [MTF] {tf}: fail rate {fail_rate}% za wysoki — pomijam")
        return None

    # --- 2. FILTR WAGI WZORCA (self-learning) ---
    direction_str = "LONG" if current_trend == "bull" else "SHORT"
    pattern = f"{direction_str}_{current_structure}_{current_fvg_type}"
    weight = get_pattern_adjustment({"pattern": pattern})
    if weight < 0.5:
        logger.info(f"🔍 [MTF] {tf}: waga wzorca {pattern} = {weight:.2f} za niska — pomijam")
        return None

    # --- 3. SPRAWDZENIE SETUPU SMC: wymagamy przynajmniej jednego silnego sygnału ---
    has_grab_mss = analysis.get('liquidity_grab') and analysis.get('mss')
    has_fvg = current_fvg_type in ("bullish", "bearish")
    has_bos = analysis.get('bos_bullish') or analysis.get('bos_bearish')
    has_choch = analysis.get('choch_bullish') or analysis.get('choch_bearish')
    has_dbr_rbd = analysis.get('dbr_rbd_type') in ("DBR", "RBD")
    has_ob = analysis.get('ob_price') is not None and analysis.get('ob_price') != current_price

    # Wymóg: co najmniej Liquidity Grab+MSS, albo FVG + (BOS/CHoCH/OB), albo DBR/RBD
    strong_setup = (
        has_grab_mss
        or (has_fvg and (has_bos or has_choch or has_ob))
        or has_dbr_rbd
    )
    if not strong_setup:
        logger.debug(f"🔍 [MTF] {tf}: brak silnego setupu SMC — pomijam")
        return None

    # --- 4. OBLICZENIE POZYCJI (SL/TP/kierunek) ---
    # Pass empty DataFrame to skip redundant ML candle fetch inside calculate_position —
    # ML validation is done separately in step 5 with the correct TF candles.
    try:
        import pandas as _pd
        pos = calculate_position(analysis, balance, currency, "", df=_pd.DataFrame())
    except Exception as e:
        logger.warning(f"🔍 [MTF] {tf}: błąd calculate_position: {e}")
        return None

    if pos.get("direction") == "CZEKAJ":
        logger.info(f"🔍 [MTF] {tf}: pozycja CZEKAJ — {pos.get('reason', '?')}")
        return None

    direction = pos['direction']
    entry = pos['entry']
    sl = pos['sl']
    tp = pos['tp']
    lot = pos.get('lot', 0.01)
    logic = pos.get('logic', '')

    # --- 5. ML ENSEMBLE VALIDATION (opcjonalne — nie blokuje, ale loguje) ---
    ml_info = ""
    try:
        from src.data_sources import get_provider
        from src.ensemble_models import get_ensemble_prediction

        provider = get_provider()
        candles = provider.get_candles('XAU/USD', tf, 200)

        if candles is not None and not candles.empty:
            ensemble = get_ensemble_prediction(
                df=candles,
                smc_trend=current_trend,
                current_price=current_price,
                balance=10000,
                initial_balance=10000,
                position=0
            )
            if ensemble['confidence'] > 0.7:
                ml_info = f"ML: {ensemble['ensemble_signal']} ({ensemble['confidence']:.0%})"
                logger.info(f"✅ [MTF] {tf}: {ml_info}")
            elif ensemble['confidence'] < 0.3:
                logger.info(f"⚠️ [MTF] {tf}: ML niska pewność {ensemble['confidence']:.0%} — ostrzeżenie")
    except Exception as e:
        logger.debug(f"[MTF] {tf}: ML ensemble validation skipped: {e}")

    # --- 6. SETUP WAŻNY — zwróć parametry trade'a ---
    logger.info(
        f"🎯 [MTF] ZNALEZIONO TRADE na {tf}! "
        f"{direction} @ {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | {logic}"
    )

    return {
        "tf": tf,
        "tf_label": TF_LABELS.get(tf, tf.upper()),
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "lot": lot,
        "logic": logic,
        "trend": current_trend,
        "rsi": current_rsi,
        "structure": current_structure,
        "fvg": current_fvg,
        "fvg_type": current_fvg_type,
        "pattern": pattern,
        "fail_rate": fail_rate,
        "price": current_price,
        "ml_info": ml_info,
        "analysis": analysis,
    }


def cascade_mtf_scan(db, balance: float = 10000, currency: str = "USD") -> dict | None:
    """
    Kaskadowe skanowanie multi-timeframe: 4h → 1h → 15m → 5m.
    Zwraca dict z parametrami trade'a na pierwszym TF z ważnym setupem, lub None.

    NIE zapisuje do bazy, NIE wysyła alertów — to odpowiedzialność wywołującego.
    Sprawdza dostępność kredytów API przed każdym TF.

    Args:
        db: instancja NewsDB
        balance: balance portfela (do calculate_position)
        currency: waluta portfela

    Returns:
        dict z parametrami trade'a lub None jeśli żaden TF nie dał sygnału
    """
    logger.info(f"🔎 [MTF] Start kaskady: {' → '.join(SCAN_TIMEFRAMES)}")

    for tf in SCAN_TIMEFRAMES:
        logger.info(f"🔎 [MTF] Sprawdzam {TF_LABELS.get(tf, tf)}...")

        # Credit pre-check per TF (candles + USD/JPY ≈ 2 credits)
        try:
            from src.api_optimizer import get_rate_limiter
            can, _ = get_rate_limiter().can_use_credits(2)
            if not can:
                logger.info(f"🔎 [MTF] Credits low — przerywam kaskadę na {tf}")
                break
        except Exception:
            pass  # API optimizer not initialized (tests / early startup)

        result = _evaluate_tf_for_trade(tf, db, balance=balance, currency=currency)
        if result is not None:
            logger.info(f"✅ [MTF] Trade znaleziony na {TF_LABELS.get(tf, tf)} — przerywam kaskadę.")
            return result
        else:
            logger.debug(f"⏭️ [MTF] Brak setupu na {TF_LABELS.get(tf, tf)} — szukam niżej...")

    logger.info("🔎 [MTF] Brak ważnego setupu na żadnym TF.")
    return None


async def scan_market_task(context):
    """
    Zadanie cykliczne (co 15 min).
    Multi-Timeframe Cascade: przeszukuje 4h → 1h → 15m → 5m.
    Jeśli na danym TF znajdzie ważny setup, stawia trade i przerywa kaskadę.

    Dodatkowo:
    - Prefetch wszystkich timeframe'ów na start (oszczędność kredytów)
    - Alerty o liquidity grab na M5
    - Alerty o zmianach trendu i nowych strefach FVG
    - Heartbeat co 30 min
    """
    try:
        # Prefetch all timeframes first (populates cache, reduces subsequent API calls)
        try:
            from src.data_sources import get_provider
            provider = get_provider()
            provider.prefetch_all_timeframes('XAU/USD')
        except Exception as e:
            logger.debug(f"Prefetch skipped: {e}")

        from src.database import NewsDB
        db = NewsDB()

        # Odczytaj balans portfela z bazy (jak robi _background_scanner w api/main.py)
        scan_balance = 10000.0
        scan_currency = "USD"
        try:
            bal = db.get_param("portfolio_balance")
            if bal and float(bal) > 0:
                scan_balance = float(bal)
            try:
                _row = db._query_one(
                    "SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_currency_text'"
                )
                if _row and _row[0]:
                    scan_currency = str(_row[0])
            except Exception:
                pass
        except Exception:
            pass

        # =====================================================================
        # KASKADA MULTI-TIMEFRAME: 4h → 1h → 15m → 5m
        # =====================================================================
        trade_found = cascade_mtf_scan(db, balance=scan_balance, currency=scan_currency)

        # =====================================================================
        # JEŚLI ZNALEZIONO TRADE — STAWIAMY GO
        # =====================================================================
        if trade_found:
            tf = trade_found['tf']
            tf_label = trade_found['tf_label']
            direction = trade_found['direction']
            entry = trade_found['entry']
            sl = trade_found['sl']
            tp = trade_found['tp']
            lot = trade_found['lot']
            logic = trade_found['logic']
            trend = trade_found['trend']
            rsi = trade_found['rsi']
            structure = trade_found['structure']
            pattern = trade_found['pattern']
            ml_info = trade_found['ml_info']
            analysis = trade_found['analysis']

            # Deduplikacja — nie stawiaj tego samego trade'a dwa razy
            trade_key = _hash(f"mtf_{direction}_{entry:.1f}_{tf}")
            if not db.is_news_processed(trade_key):
                # Zapisz trade do bazy (OPEN)
                structure_desc = (
                    f"[{tf_label}] Grab:{analysis.get('liquidity_grab')}, "
                    f"MSS:{analysis.get('mss')}, FVG:{analysis.get('fvg_type')}, "
                    f"DBR:{analysis.get('dbr_rbd_type')}"
                )
                db.log_trade(
                    direction=direction,
                    price=entry,
                    sl=sl,
                    tp=tp,
                    rsi=rsi,
                    trend=trend,
                    structure=structure_desc,
                    pattern=pattern,
                    lot=lot,
                )
                logger.info(f"💾 [SCANNER] Trade zapisany do trades: {direction} @ {entry:.2f}")

                # Zapisz sygnał do scanner_signals
                db.save_scanner_signal(
                    direction=direction,
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    rsi=rsi,
                    trend=trend,
                    structure=f"MTF_{tf_label}_{structure}"
                )
                logger.info(f"📡 [SCANNER] Sygnał MTF zapisany do scanner_signals.")

                # Wyślij alert Telegram
                ml_line = f"\n🤖 {ml_info}" if ml_info else ""
                alert_msg = (
                    f"🎯 *NOWY TRADE — Kaskada MTF*\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"⏱ Timeframe: *{tf_label}*\n"
                    f"🚀 Kierunek: *{direction}*\n"
                    f"📍 Wejście: `{entry:.2f}$`\n"
                    f"🛑 SL: `{sl:.2f}$`\n"
                    f"✅ TP: `{tp:.2f}$`\n"
                    f"📊 Lot: `{lot}`\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📈 Trend: `{trend}` | RSI: `{rsi:.1f}`\n"
                    f"🏗️ Struktura: `{structure}`\n"
                    f"💡 Logika: _{logic}_{ml_line}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔎 _Przeszukano: {' → '.join(SCAN_TIMEFRAMES)}_\n"
                    f"✅ _Znaleziono na: {tf_label}_"
                )
                send_telegram_alert(alert_msg)
                db.mark_news_as_processed(trade_key)
            else:
                logger.info(f"📡 [SCANNER] Trade {direction}@{entry:.1f} na {tf_label} już deduplikowany — pomijam.")

        # =====================================================================
        # DODATKOWE ALERTY (niezależne od kaskady)
        # =====================================================================
        # Analiza bazowego TF użytkownika (na potrzeby alertów trendu/FVG)
        base_tf = USER_PREFS.get('tf', '15m')
        analysis_base = get_smc_analysis(base_tf)
        if analysis_base:
            current_trend = analysis_base['trend']
            current_fvg = analysis_base['fvg']
            current_price = analysis_base['price']
            current_rsi = analysis_base['rsi']
            current_structure = analysis_base.get('structure', 'Stable')

            # SL/TP dla alertów (awaryjne z ATR)
            _atr = analysis_base.get('atr', 5.0)
            from src.finance import calculate_position
            try:
                _pos = calculate_position(analysis_base, 10000, "USD", TD_API_KEY)
                current_sl = _pos.get('sl', current_price)
                current_tp = _pos.get('tp', current_price)
            except Exception:
                if current_trend == 'bull':
                    current_sl = round(current_price - _atr, 2)
                    current_tp = round(current_price + _atr * 2, 2)
                else:
                    current_sl = round(current_price + _atr, 2)
                    current_tp = round(current_price - _atr * 2, 2)

            # --- ALERT LIQUIDITY GRAB NA M5 ---
            analysis_m5 = get_smc_analysis("5m")
            if analysis_m5 and analysis_m5.get('liquidity_grab'):
                alert_key = _hash(f"grab_m5_{analysis_m5['liquidity_grab_dir']}_{analysis_m5['price']:.1f}")
                if not db.is_news_processed(alert_key):
                    grab_msg = f"⚡ *LIQUIDITY GRAB NA M5!*\nKierunek: *{analysis_m5['liquidity_grab_dir'].upper()}*\nCena: {analysis_m5['price']}$\n"
                    if analysis_m5['liquidity_grab_dir'] == "bullish":
                        grab_msg += "Oczekuj szybkiego powrotu w górę – szukaj LONG na M5 FVG/OB."
                    else:
                        grab_msg += "Oczekuj szybkiego spadku – szukaj SHORT na M5 FVG/OB."
                    send_telegram_alert(grab_msg)
                    db.mark_news_as_processed(alert_key)

            # --- ALERT ZMIANY TRENDU ---
            with LAST_STATUS_LOCK:
                last_trend = LAST_STATUS.get("trend")

            if last_trend is not None and current_trend != last_trend:
                alert_key = _hash(f"trend_{current_trend}_{current_structure}")
                fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)

                if not db.is_news_processed(alert_key):
                    struct_icon = "🏗️" if "ChoCH" in current_structure else "⚡"
                    alert_msg = (
                        f"⚠️ *ZMIANA TRENDU: GOLD*\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"Nowy Kierunek: *{current_trend.upper()}*\n"
                        f"{struct_icon} Struktura: `{current_structure}`\n"
                        f"📊 RSI: `{current_rsi}` | Szansa na fail: `{fail_rate}%`\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"📥 _Sprawdź DASHBOARD dla parametrów._"
                    )
                    send_telegram_alert(alert_msg)
                    db.mark_news_as_processed(alert_key)

                    direction = "LONG" if current_trend.lower() == "bull" else "SHORT"
                    db.save_scanner_signal(
                        direction=direction,
                        entry=current_price,
                        sl=current_sl,
                        tp=current_tp,
                        rsi=current_rsi,
                        trend=current_trend,
                        structure=current_structure
                    )
                    logger.info(f"📡 [SCANNER] Zapisano sygnał zmiany trendu {direction}.")

            # --- ALERT NOWEJ STREFY FVG ---
            with LAST_STATUS_LOCK:
                last_fvg = LAST_STATUS.get("fvg")

            if (current_fvg not in ["None", "Brak", None] and current_fvg != last_fvg):
                fvg_lower_str = current_fvg.lower()

                if "bull" in fvg_lower_str or "up" in fvg_lower_str:
                    kierunek = "BULLISH 🟢 (Luka wzrostowa)"
                    direction = "LONG"
                    is_serious = True
                elif "bear" in fvg_lower_str or "down" in fvg_lower_str:
                    kierunek = "BEARISH 🔴 (Luka spadkowa)"
                    direction = "SHORT"
                    is_serious = True
                else:
                    kierunek = f"WYKRYTO ({current_fvg})"
                    direction = "LONG"
                    is_serious = False

                if is_serious:
                    fvg_key = _hash(f"fvg_{current_fvg}_{current_price:.1f}")

                    if not db.is_news_processed(fvg_key):
                        fvg_msg = (
                            f"⚡ *ISTOTNY FVG: GOLD ({base_tf})*\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"🧭 Typ: *{kierunek}*\n"
                            f"💰 Cena: `{current_price}$`\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"🎯 *TARGET:* Cena prawdopodobnie wróci zamknąć tę lukę.\n"
                            f"💡 _Pamiętaj: FVG to magnes dla ceny (Imbalance)._"
                        )
                        send_telegram_alert(fvg_msg)
                        db.mark_news_as_processed(fvg_key)

                        db.save_scanner_signal(
                            direction=direction,
                            entry=current_price,
                            sl=current_sl,
                            tp=current_tp,
                            rsi=current_rsi,
                            trend=current_trend,
                            structure=f"FVG_{current_fvg}"
                        )
                        logger.info(f"📡 [SCANNER] Zapisano sygnał FVG {direction}.")

            # --- AKTUALIZACJA STANU (THREAD-SAFE) ---
            with LAST_STATUS_LOCK:
                LAST_STATUS["trend"] = current_trend
                LAST_STATUS["fvg"] = current_fvg

        # =====================================================================
        # HEARTBEAT (co 30 min) — jeśli nie znaleziono trade'a
        # =====================================================================
        if not trade_found:
            _now = _time.time()
            _last_hb = getattr(scan_market_task, '_last_heartbeat', 0)
            if _now - _last_hb >= 1800:  # 30 min
                # Użyj dowolnej dostępnej analizy do heartbeat
                hb_analysis = analysis_base or get_smc_analysis("15m")
                if hb_analysis:
                    from src.finance import calculate_position
                    hb_trend = hb_analysis['trend']
                    hb_price = hb_analysis['price']
                    hb_rsi = hb_analysis['rsi']
                    hb_structure = hb_analysis.get('structure', 'Stable')
                    direction_hb = "LONG" if hb_trend == "bull" else "SHORT"
                    try:
                        hb_pos = calculate_position(hb_analysis, 10000, "USD", TD_API_KEY)
                        hb_sl = hb_pos.get('sl', hb_price - 10)
                        hb_tp = hb_pos.get('tp', hb_price + 20)
                    except Exception:
                        _atr = hb_analysis.get('atr', 5.0)
                        if hb_trend == 'bull':
                            hb_sl = round(hb_price - _atr, 2)
                            hb_tp = round(hb_price + _atr * 2, 2)
                        else:
                            hb_sl = round(hb_price + _atr, 2)
                            hb_tp = round(hb_price - _atr * 2, 2)
                    db.save_scanner_signal(
                        direction=direction_hb,
                        entry=hb_price,
                        sl=hb_sl,
                        tp=hb_tp,
                        rsi=hb_rsi,
                        trend=hb_trend,
                        structure=hb_structure
                    )
                    scan_market_task._last_heartbeat = _now
                    logger.info(f"📡 [SCANNER] Heartbeat {direction_hb} @ ${hb_price:.2f} (żaden TF nie dał trade'a)")
            else:
                logger.debug(f"📡 [SCANNER] Heartbeat pominięty (ostatni {int(_now - _last_hb)}s temu)")

        logger.info(
            f"✅ [SCANNER] Skonczono cykl MTF. "
            f"{'Trade postawiony na ' + trade_found['tf_label'] if trade_found else 'Brak setupu na żadnym TF.'}"
        )

    except Exception as e:
        logger.error(f"❌ [SCANNER] Błąd: {e}")


async def resolve_trades_task(context):
    """
    Poprawiona wersja: Przy LOSS zapisuje powód i okoliczności do bazy.
    """
    from src.database import NewsDB
    db = NewsDB()

    # 1. POBIERANIE CENY (przez DataProvider — rate limited, cached, WS fallback)
    try:
        from src.data_sources import get_provider
        provider = get_provider()
        price_data = provider.get_current_price('XAU/USD')
        if price_data is None or 'price' not in price_data:
            logger.warning(f"⚠️ [RESOLVER] Brak ceny z DataProvider")
            return
        current_price = float(price_data['price'])
        logger.info(f"🔍 [RESOLVER] Aktualna cena XAU/USD: {current_price} (source: {price_data.get('source', 'unknown')})")

    except Exception as e:
        logger.error(f"❌ [RESOLVER] Błąd pobierania ceny: {e}")
        return

    # 2. POBIERANIE I ROZLICZANIE POZYCJI
    try:
        open_trades = db.get_open_trades()
        if not open_trades:
            return

        # Pobierz aktualny kontekst rynkowy raz dla wszystkich pozycji
        try:
            analysis = get_smc_analysis(USER_PREFS['tf'])
            market_snapshot = (
                f"Cena: {current_price} | "
                f"Trend: {analysis.get('trend', '?')} | "
                f"RSI: {analysis.get('rsi', '?')} | "
                f"Struktura: {analysis.get('structure', '?')} | "
                f"FVG: {analysis.get('fvg', '?')}"
            ) if analysis else f"Cena: {current_price}"
        except Exception:
            market_snapshot = f"Cena: {current_price}"

        for trade in open_trades:
            t_id, direction, entry, sl, tp = trade
            status = None

            dir_clean = str(direction).strip().upper()

            if "LONG" in dir_clean:
                if current_price >= float(tp):
                    status = "PROFIT"
                elif current_price <= float(sl):
                    status = "LOSS"
            elif "SHORT" in dir_clean:
                if current_price <= float(tp):
                    status = "PROFIT"
                elif current_price >= float(sl):
                    status = "LOSS"

            if status:
                # Oblicz profit/loss w dolarach przed zapisem
                try:
                    entry_f = float(entry or 0)
                    sl_f = float(sl or 0)
                    tp_f = float(tp or 0)
                    if status == "PROFIT":
                        profit_val = round(abs(tp_f - entry_f), 2) if entry_f > 0 else 0
                    else:  # LOSS
                        profit_val = round(-abs(entry_f - sl_f), 2) if entry_f > 0 else 0
                except (ValueError, TypeError):
                    profit_val = 0

                db.update_trade_status(t_id, status)
                db.update_trade_profit(t_id, profit_val)

                # ========== NOWE: aktualizacja statystyk sesji ==========
                if status in ("PROFIT", "LOSS"):
                    db.cursor.execute("SELECT pattern, session FROM trades WHERE id = ?", (t_id,))
                    row = db.cursor.fetchone()
                    if row and row[0]:
                        pattern = row[0]
                        session = row[1] or "Unknown"
                        db.update_session_stats(pattern, session, status)

                if status in ("PROFIT", "LOSS"):
                    from src.self_learning import update_factor_weights
                    update_factor_weights(t_id, status)

                    # Aktualizuj wagi ensemble na podstawie wyników modeli
                    try:
                        from src.ensemble_models import update_ensemble_weights
                        factors = db.get_trade_factors(t_id)
                        correct = []
                        incorrect = []

                        # SMC — zawsze używane
                        if status == "PROFIT":
                            correct.append("smc")
                        else:
                            incorrect.append("smc")

                        # ML — sprawdź czy czynniki ML były obecne i czy kierunek się zgadzał
                        # Czynniki ML: ichimoku_bull/bear, rsi_divergence, engulfing, pin_bar, ml_ensemble_*
                        ml_factors_bull = any(factors.get(k) for k in ('ichimoku_bull', 'ml_ensemble_long'))
                        ml_factors_bear = any(factors.get(k) for k in ('ichimoku_bear', 'ml_ensemble_short'))

                        has_ml_signal = ml_factors_bull or ml_factors_bear
                        if has_ml_signal:
                            ml_agreed_with_direction = (
                                (ml_factors_bull and "LONG" in dir_clean) or
                                (ml_factors_bear and "SHORT" in dir_clean)
                            )
                            if status == "PROFIT" and ml_agreed_with_direction:
                                correct.append("lstm")
                                correct.append("xgb")
                            elif status == "LOSS" and ml_agreed_with_direction:
                                incorrect.append("lstm")
                                incorrect.append("xgb")
                            elif status == "PROFIT" and not ml_agreed_with_direction:
                                # ML sygnalizowało przeciwny kierunek ale trade wygrał (SMC miało rację)
                                incorrect.append("lstm")
                                incorrect.append("xgb")

                        if correct or incorrect:
                            update_ensemble_weights(correct, incorrect)
                    except Exception as e:
                        logger.debug(f"Ensemble weight update skipped: {e}")

                    # Aktualizuj statystyki reżimu
                    try:
                        trade_row = db.cursor.execute(
                            "SELECT session, factors FROM trades WHERE id = ?", (t_id,)
                        )
                        trow = db.cursor.fetchone()
                        if trow:
                            import json
                            tsession = trow[0] or "Unknown"
                            tfactors = json.loads(trow[1]) if trow[1] else {}
                            regime = "neutralny"
                            if tfactors.get("macro"):
                                regime = "zielony" if "LONG" in dir_clean else "czerwony"
                            db.update_regime_stats(regime, tsession, dir_clean, status)
                    except Exception as e:
                        logger.debug(f"Regime stats update skipped: {e}")

                db.cursor.execute("SELECT pattern FROM trades WHERE id = ?", (t_id,))
                pattern = db.cursor.fetchone()
                pattern = pattern[0] if pattern else None
                analysis_data = {"pattern": pattern}
                from src.self_learning import update_pattern_weight
                update_pattern_weight(analysis_data, status)

                exit_price = float(tp) if status == "PROFIT" else float(sl)

                # ← ZAPISUJE POWÓD I OKOLICZNOŚCI PRZEGRANEJ
                if status == "LOSS":
                    reason = (
                        f"Cena dotknęła SL ({sl}$). "
                        f"Wejście było na {entry}$, "
                        f"kierunek: {direction}."
                    )
                    db.log_loss_details(
                        trade_id=t_id,
                        reason=reason,
                        market_condition=market_snapshot
                    )
                    logger.info(f"📝 [RESOLVER] Zapisano okoliczności straty dla pozycji {t_id}.")

                icon = "✅" if status == "PROFIT" else "❌"
                msg = (
                    f"{icon} *POZYCJA ROZSTRZYGNIĘTA!*\n"
                    f"ID: `{t_id}` | Kierunek: {direction}\n"
                    f"Wynik: *{status}*\n"
                    f"Wejście: `{entry}` | Wyjście: `{exit_price}`"
                )
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                logger.info(f"💰 [RESOLVER] Zamknięto pozycję {t_id} jako {status}")

    except Exception as e:
        logger.error(f"🚨 [RESOLVER] Błąd podczas sprawdzania pozycji: {e}")
