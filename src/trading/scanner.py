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

from src.core.logger import logger
from src.core.config import TOKEN, CHAT_ID, USER_PREFS, LAST_STATUS, LAST_STATUS_LOCK, TD_API_KEY
from src.trading.smc_engine import get_smc_analysis

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


def extract_factors(analysis: dict, direction: str) -> dict:
    """
    Wyciaga czynniki tradingowe z analizy SMC do zapisu w trades.factors.
    Uzywane przez background scanner, quick-trade, i log_trade.
    """
    factors = {}
    if not analysis:
        return factors

    # BOS
    if (direction == "LONG" and analysis.get('bos_bullish')) or \
       (direction == "SHORT" and analysis.get('bos_bearish')):
        factors['bos'] = 1

    # CHoCH
    if (direction == "LONG" and analysis.get('choch_bullish')) or \
       (direction == "SHORT" and analysis.get('choch_bearish')):
        factors['choch'] = 1

    # Order blocks
    ob_list = analysis.get('order_blocks', [])
    if ob_list:
        factors['ob_count'] = min(len(ob_list), 3)

    ob_main = analysis.get('ob_price')
    if ob_main and analysis.get('price'):
        if (direction == "LONG" and ob_main < analysis['price']) or \
           (direction == "SHORT" and ob_main > analysis['price']):
            factors['ob_main'] = 1

    # FVG
    fvg_type = analysis.get('fvg_type')
    if (direction == "LONG" and fvg_type == "bullish") or \
       (direction == "SHORT" and fvg_type == "bearish"):
        factors['fvg'] = 1

    # Liquidity Grab + MSS
    if analysis.get('liquidity_grab') and analysis.get('mss'):
        grab_dir = analysis.get('liquidity_grab_dir')
        if (direction == "LONG" and grab_dir == "bullish") or \
           (direction == "SHORT" and grab_dir == "bearish"):
            factors['grab_mss'] = 1

    # DBR/RBD
    dbr_type = analysis.get('dbr_rbd_type')
    if (direction == "LONG" and dbr_type == "DBR") or \
       (direction == "SHORT" and dbr_type == "RBD"):
        factors['dbr_rbd'] = 1

    # Macro
    macro = analysis.get('macro_regime')
    if (direction == "LONG" and macro == "zielony") or \
       (direction == "SHORT" and macro == "czerwony"):
        factors['macro'] = 1

    # RSI optimal zone
    rsi = analysis.get('rsi')
    if rsi:
        if direction == "LONG" and 40 <= rsi <= 50:
            factors['rsi_opt'] = 1
        elif direction == "SHORT" and 50 <= rsi <= 60:
            factors['rsi_opt'] = 1

    # RSI Divergence
    if (direction == "LONG" and analysis.get('rsi_div_bull')) or \
       (direction == "SHORT" and analysis.get('rsi_div_bear')):
        factors['rsi_divergence'] = 1

    # Engulfing
    eng = analysis.get('engulfing', False)
    if (direction == "LONG" and eng == 'bullish') or \
       (direction == "SHORT" and eng == 'bearish'):
        factors['engulfing'] = 1

    # Pin bar
    pb = analysis.get('pin_bar', False)
    if (direction == "LONG" and pb == 'bullish') or \
       (direction == "SHORT" and pb == 'bearish'):
        factors['pin_bar'] = 1

    # Ichimoku
    if direction == "LONG" and analysis.get('ichimoku_above_cloud'):
        factors['ichimoku_bull'] = 1
    elif direction == "SHORT" and analysis.get('ichimoku_below_cloud'):
        factors['ichimoku_bear'] = 1

    # Killzone / session
    if analysis.get('is_killzone'):
        factors['killzone'] = 1

    return factors

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

def _log_rejection(db, tf, direction, price, reason, filter_name,
                   confluence_count=0, rsi=0, trend="", pattern="", atr=0):
    """Helper do zapisu odrzuconego setupu do bazy (fire-and-forget)."""
    try:
        db.log_rejected_setup(
            timeframe=tf, direction=direction, price=price,
            rejection_reason=reason, filter_name=filter_name,
            confluence_count=confluence_count, rsi=rsi,
            trend=trend, pattern=pattern, atr=atr
        )
    except (AttributeError, TypeError, Exception) as e:
        logger.debug(f"Rejection log failed: {e}")


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
    from src.trading.finance import calculate_position
    from src.learning.self_learning import get_pattern_adjustment

    # ─── EVENT GUARD: block new entries 15 min before high-impact news ───
    # Gold moves 2-3% in 30 sec on NFP/CPI/FOMC — SL hits before signal
    # matures. Better to miss the trade than guarantee a losing one.
    try:
        from src.data.news import get_imminent_high_impact_events
        imminent = get_imminent_high_impact_events(minutes_window=15)
        if imminent:
            titles = ", ".join(e.get("event", "?") for e in imminent[:2])
            logger.info(f"⏸️ [EVENT GUARD] {tf}: blokuję — high-impact event w <15min: {titles}")
            return None
    except Exception as _e:
        logger.debug(f"Event guard check failed: {_e}")  # soft-fail, don't block trading

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
    except (ImportError, AttributeError, TypeError, ValueError):
        pass  # persistent_cache not available outside FastAPI context
    current_structure = analysis.get('structure', 'Stable')
    current_fvg = analysis.get('fvg')
    current_fvg_type = analysis.get('fvg_type')

    # --- 0b. FILTR MINIMALNEJ ZMIENNOŚCI (ATR) ---
    current_atr = analysis.get('atr', 0)
    if current_atr < 2.0:
        logger.info(f"🔍 [MTF] {tf}: ATR={current_atr:.2f} za niski (min 2.0) — zbyt mała zmienność")
        _log_rejection(db, tf, "LONG" if current_trend == "bull" else "SHORT",
                       current_price, f"ATR={current_atr:.2f}<2.0", "atr_filter",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 0c. FILTR RSI EXTREME — nie wchodź w pozycję przeciw momentum ---
    if current_trend == "bull" and current_rsi > 75:
        logger.info(f"[MTF] {tf}: RSI={current_rsi:.0f} > 75 (wykupiony) — nie LONG na szczycie")
        _log_rejection(db, tf, "LONG", current_price, f"RSI={current_rsi:.0f}>75", "rsi_extreme",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None
    if current_trend == "bear" and current_rsi < 25:
        logger.info(f"[MTF] {tf}: RSI={current_rsi:.0f} < 25 (wyprzedany) — nie SHORT na dnie")
        _log_rejection(db, tf, "SHORT", current_price, f"RSI={current_rsi:.0f}<25", "rsi_extreme",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 1. FILTR FAIL RATE (tightened: 75% → 65%) ---
    fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)
    if fail_rate > 65:
        logger.info(f"[MTF] {tf}: fail rate {fail_rate}% za wysoki (max 65%) — pomijam")
        _log_rejection(db, tf, "LONG" if current_trend == "bull" else "SHORT",
                       current_price, f"fail_rate={fail_rate}%>65%", "fail_rate",
                       rsi=current_rsi, trend=current_trend, atr=current_atr)
        return None

    # --- 2. FILTR WAGI WZORCA (relaxed back: 0.6 → 0.5 on 2026-04-14) ---
    # User reported manually catching $20-30 SHORT moves on gold today that
    # the scanner rejected 8× with "SHORT_Stable_bearish weight=0.50 < 0.6".
    # The 0.6 threshold was a prior tightening from 0.5; revert it so
    # moderately-weighted patterns can trade and self-learning accumulates
    # data. If a pattern truly stops working, update_pattern_weight() will
    # drag it below 0.5 and auto-block naturally.
    direction_str = "LONG" if current_trend == "bull" else "SHORT"
    pattern = f"{direction_str}_{current_structure}_{current_fvg_type}"
    weight = get_pattern_adjustment({"pattern": pattern})
    if weight < 0.5:
        logger.info(f"[MTF] {tf}: waga wzorca {pattern} = {weight:.2f} za niska (min 0.5) — pomijam")
        _log_rejection(db, tf, direction_str, current_price,
                       f"pattern_weight={weight:.2f}<0.5", "pattern_weight",
                       rsi=current_rsi, trend=current_trend, pattern=pattern, atr=current_atr)
        return None

    # --- 3. SPRAWDZENIE SETUPU SMC: wymagamy silnej konfluencji ---
    has_grab_mss = analysis.get('liquidity_grab') and analysis.get('mss')
    has_fvg = current_fvg_type in ("bullish", "bearish")
    has_bos = analysis.get('bos_bullish') or analysis.get('bos_bearish')
    has_choch = analysis.get('choch_bullish') or analysis.get('choch_bearish')
    has_dbr_rbd = analysis.get('dbr_rbd_type') in ("DBR", "RBD")
    has_ob = analysis.get('ob_price') is not None and analysis.get('ob_price') != current_price

    # RSI Divergence — silny kontrtrendowy sygnał
    has_rsi_div = (
        (current_trend == "bull" and analysis.get('rsi_div_bull')) or
        (current_trend == "bear" and analysis.get('rsi_div_bear'))
    )
    # Engulfing pattern confirmation
    has_engulfing = (
        (current_trend == "bull" and analysis.get('engulfing') == "bullish") or
        (current_trend == "bear" and analysis.get('engulfing') == "bearish")
    )

    # Count confluence signals
    confluence_count = sum([
        bool(has_grab_mss),
        bool(has_fvg),
        bool(has_bos or has_choch),
        bool(has_dbr_rbd),
        bool(has_ob),
        bool(has_rsi_div),
        bool(has_engulfing),
    ])

    # Backtest isolation flag — used in both step 3a (direction_conflict
    # scalp soften) and step 3 below (confluence/stable). Kept here (before
    # first usage) so scalp_soften doesn't UnboundLocalError.
    import os as _os_bt
    _relax = (
        _os_bt.environ.get("QUANT_BACKTEST_RELAX") == "1"
        and _os_bt.environ.get("QUANT_BACKTEST_MODE") == "1"
    )

    # --- 3a. DIRECTIONAL ALIGNMENT CHECK (new) ---
    # BOS/CHoCH must agree with trade direction — don't trade against structure
    if has_bos or has_choch:
        bos_bullish = analysis.get('bos_bullish', False)
        bos_bearish = analysis.get('bos_bearish', False)
        choch_bullish = analysis.get('choch_bullish', False)
        choch_bearish = analysis.get('choch_bearish', False)

        structure_bullish = bos_bullish or choch_bullish
        structure_bearish = bos_bearish or choch_bearish

        # Scalp mode (5m): structure conflict is a RISK SIGNAL, not a hard block.
        # Small SL ($2-3) limits downside; halving lot further caps it. Slow
        # TFs (H4/H1/M15) still hard-block because their larger SL makes
        # fighting structure genuinely expensive.
        _scalp_soften = str(tf) == "5m" and not _relax
        if direction_str == "LONG" and structure_bearish and not structure_bullish:
            if _scalp_soften:
                logger.warning(f"[MTF] {tf}: LONG vs BOS bearish — SCALP halve risk (soft)")
                analysis['_scalp_risk_halve'] = True
            else:
                logger.info(f"[MTF] {tf}: LONG but BOS/CHoCH is bearish — structural conflict")
                _log_rejection(db, tf, direction_str, current_price,
                               "structure_direction_conflict", "directional_alignment",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
        if direction_str == "SHORT" and structure_bullish and not structure_bearish:
            if _scalp_soften:
                logger.warning(f"[MTF] {tf}: SHORT vs BOS bullish — SCALP halve risk (soft)")
                analysis['_scalp_risk_halve'] = True
            else:
                logger.info(f"[MTF] {tf}: SHORT but BOS/CHoCH is bullish — structural conflict")
                _log_rejection(db, tf, direction_str, current_price,
                               "structure_direction_conflict", "directional_alignment",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None

    # --- 3b. CONFLUENCE THRESHOLD (tightened: 3→4 base, grab+2→grab+3, dbr+2→dbr+3) ---
    # "Stable" structure = konsolidacja = 0% win rate historycznie — blokuj.
    #
    # BACKTEST RELAXATION: with yfinance-only data (no Twelve Data USD/JPY
    # correlation, no Myfxbook macro, no news sentiment feedback) we can't
    # reach confluence=3 in production setups. Lower to 2 and allow Stable.
    # Directional alignment + RSI extreme stay strict — those are reality
    # checks, not data-source-dependent.
    #
    # SAFETY: _relax already initialized at top of function (step 3a).
    # Double-gate — requires BOTH env vars. QUANT_BACKTEST_MODE is only set
    # by src.backtest.isolation.enforce_isolation(), which runs in a separate
    # process with a separate DB file. Production API never calls
    # enforce_isolation(), so it never sees either flag.
    # Backtest: threshold=1 — yfinance data produces max confluence=2-3,
    # and we lose news/macro signals (worth ~1-2 confluence in live).
    # At threshold=2 we got 0.5 trades/day; target is 2-3/day for
    # meaningful statistical sample. Directional alignment + RSI extreme
    # still strict — those protect against bad trades regardless.
    _min_conf = 1 if _relax else 3

    structure = analysis.get('structure', 'Stable')
    is_stable = 'Stable' in str(structure)

    # --- 5m special case (2026-04-14) ---
    # User empirically catches $10-20 moves on 5m during intraday. Higher
    # TFs correctly wait for full swing setups (confluence=3 + non-Stable)
    # but 5m's granularity means Stable often IS the relevant context
    # (short holding time, small SL). Lower bar for 5m specifically:
    #   - min_conf 2 instead of 3
    #   - don't block on structure=Stable
    # Other filters (RSI extreme, directional alignment, ML ensemble
    # validation at line 421, pattern_weight, event guard, etc.) still
    # apply — so we're not opening the flood gates, just letting a scalp
    # setup through when one of the slower TFs isn't giving us anything.
    if str(tf) == "5m" and not _relax:
        # 5m scalp: single price-action factor (pin bar, engulfing, FVG
        # retest etc.) is a legitimate scalp trigger. Raising the bar to 2
        # was cutting ~29 setups/13h that the user saw on the chart.
        # Other filters (direction_conflict, RSI, ATR, macro, ML ensemble,
        # setup_quality, event guard) still apply — so we're accepting
        # thinner SMC confirmation, not a flood of junk.
        _min_conf = 1
        _allow_stable_5m = True
    else:
        _allow_stable_5m = False

    # Asian session (typically 00:00-08:00 CEST) is structurally a ranging market
    # for XAU/USD — "Stable" is the DEFAULT state, not a warning sign. Blocking
    # Stable in Asian killed ~230 setups across H4/H1/M15 overnight. Allow it
    # across all TFs when session = asian, on top of the 5m-always exception.
    _session = (analysis.get('session') or '').lower()
    _allow_stable_asian = _session == 'asian'

    strong_setup = (
        (has_grab_mss and confluence_count >= _min_conf)   # premium: grab+mss + N confirmations
        or (has_dbr_rbd and confluence_count >= _min_conf)  # DBR/RBD + N confirmations
        or confluence_count >= _min_conf                     # standalone: N+ signals required
    )
    # Stable is NOT an automatic block when: relaxed mode, 5m scalp, or asian session
    block_stable = (
        is_stable and not _relax
        and not _allow_stable_5m and not _allow_stable_asian
    )

    if not strong_setup or block_stable:
        reason = "structure=Stable (chop)" if block_stable else f"confluence={confluence_count}<{_min_conf}"
        logger.debug(f"[MTF] {tf}: brak silnego setupu ({reason}) -- pomijam")
        _log_rejection(db, tf, direction_str, current_price, reason, "confluence",
                       confluence_count=confluence_count, rsi=current_rsi,
                       trend=current_trend, pattern=pattern, atr=current_atr)
        return None

    # --- 3b. FILTR KIERUNKU vs FVG ---
    # Upewnij się że FVG potwierdza kierunek (nie shortuj z bullish FVG!)
    if has_fvg:
        if current_trend == "bull" and current_fvg_type == "bearish":
            logger.info(f"🔍 [MTF] {tf}: FVG bearish vs trend bull — konfluencja słaba, pomijam")
            return None
        if current_trend == "bear" and current_fvg_type == "bullish":
            logger.info(f"🔍 [MTF] {tf}: FVG bullish vs trend bear — konfluencja słaba, pomijam")
            return None

    # --- 4. OBLICZENIE POZYCJI (SL/TP/kierunek) ---
    # Pass empty DataFrame to skip redundant ML candle fetch inside calculate_position —
    # ML validation is done separately in step 5 with the correct TF candles.
    try:
        import pandas as _pd
        analysis['tf'] = tf  # pass TF so finance.py can apply scalp-mode on 5m
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

    # --- 5. ML ENSEMBLE VALIDATION (BLOKUJĄCE jeśli ML silnie się nie zgadza) ---
    ml_info = ""
    ensemble_result = None  # zachowaj ensemble result do zapisu w bazie
    try:
        from src.data.data_sources import get_provider
        from src.ml.ensemble_models import get_ensemble_prediction

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
            ensemble_result = ensemble  # ZACHOWAJ do użycia później
            ml_signal = ensemble.get('ensemble_signal', 'CZEKAJ')
            ml_conf = ensemble.get('confidence', 0)

            if ml_conf > 0.6 and ml_signal == direction_str:
                ml_info = f"ML: {ml_signal} ({ml_conf:.0%})"
                logger.info(f"[MTF] {tf}: ML potwierdza kierunek — {ml_info}")
            elif ml_conf > 0.45 and ml_signal != "CZEKAJ" and ml_signal != direction_str:
                # ML conflict (tightened: 50%→40%) — block earlier
                logger.warning(
                    f"[MTF] {tf}: ML ({ml_signal}, {ml_conf:.0%}) "
                    f"KONFLIKT z SMC ({direction_str}) — BLOKUJĘ trade"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"ML={ml_signal}({ml_conf:.0%}) vs SMC={direction_str}", "ml_conflict",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
            elif ml_conf < 0.3:
                logger.info(f"⚠️ [MTF] {tf}: ML niska pewność {ml_conf:.0%} — trade dozwolony ale ryzykowny")
                ml_info = f"ML: niepewny ({ml_conf:.0%})"
    except Exception as e:
        logger.debug(f"[MTF] {tf}: ML ensemble validation skipped: {e}")

    # --- 6b. SENTIMENT FILTER (opcjonalny — nie blokuje jeśli brak danych) ---
    try:
        from src.core.database import NewsDB as _SentDB
        _sent_db = _SentDB()
        # Sprawdź ostatni sentyment z news_sentiment (jeśli istnieje)
        _sent_row = _sent_db._query_one(
            "SELECT sentiment, score FROM news_sentiment ORDER BY id DESC LIMIT 1"
        )
        if _sent_row and _sent_row[0] and _sent_row[1]:
            news_sentiment = str(_sent_row[0]).lower()
            sent_conf = float(_sent_row[1]) if _sent_row[1] else 0
            # Jeśli sentyment jest silnie przeciwny do kierunku — blokuj
            if sent_conf > 0.7:
                if direction_str == "LONG" and "bearish" in news_sentiment:
                    logger.info(
                        f"📰 [MTF] {tf}: Sentyment BEARISH ({sent_conf:.0%}) "
                        f"vs LONG — BLOKUJĘ trade"
                    )
                    return None
                elif direction_str == "SHORT" and "bullish" in news_sentiment:
                    logger.info(
                        f"📰 [MTF] {tf}: Sentyment BULLISH ({sent_conf:.0%}) "
                        f"vs SHORT — BLOKUJĘ trade"
                    )
                    return None
    except Exception as e:
        logger.debug(f"[MTF] Sentiment filter skipped: {e}")

    # --- 6c. SMT DIVERGENCE FILTER — dolar i złoto nie powinny iść razem ---
    smt_warning = analysis.get('smt', 'Brak')
    if smt_warning and smt_warning != "Brak":
        logger.warning(f"⚠️ [MTF] {tf}: {smt_warning} — pomijam trade (SMT)")
        return None

    # --- 6d. PREMIUM/DISCOUNT FILTER — nie kupuj na premium, nie shortuj na discount ---
    # 5m scalp override (2026-04-14, v2): allow LONG-in-premium /
    # SHORT-in-discount on 5m when confluence_count >= 2 (matches the 5m
    # min_conf gate already enforced earlier in the function). Initial
    # override at >=3 never triggered — live setups on 5m cluster at
    # confluence=2. Lowering the bar to 2 effectively disables premium
    # filter on 5m but keeps it strict on 15m/1h/4h where premium
    # positioning genuinely kills R:R for longer holds.
    is_premium = analysis.get('is_premium', False)
    is_discount = analysis.get('is_discount', False)
    _premium_override_5m = (str(tf) == "5m" and confluence_count >= 2)
    if direction_str == "LONG" and is_premium and not _premium_override_5m:
        logger.info(f"🔍 [MTF] {tf}: LONG w strefie PREMIUM — złe R:R, pomijam")
        return None
    if direction_str == "SHORT" and is_discount and not _premium_override_5m:
        logger.info(f"🔍 [MTF] {tf}: SHORT w strefie DISCOUNT — złe R:R, pomijam")
        return None
    if _premium_override_5m and (is_premium or is_discount):
        logger.info(f"[MTF] {tf}: {direction_str} w strefie "
                    f"{'premium' if is_premium else 'discount'} dozwolone "
                    f"(confluence={confluence_count}>=3) — scalp override")

    # --- 6e. LOSS PATTERN CHECK (nowe!) ---
    try:
        from src.learning.self_learning import check_loss_pattern_match
        loss_match = check_loss_pattern_match(analysis, direction_str)
        if loss_match and loss_match['count'] >= 5:
            logger.warning(
                f"⚠️ [MTF] {tf}: Wykryto wzorzec strat: {loss_match['pattern_type']} "
                f"({loss_match['count']}x) — {loss_match['desc']}"
            )
            _log_rejection(db, tf, direction_str, current_price,
                           f"loss_pattern:{loss_match['pattern_type']}({loss_match['count']}x)",
                           "loss_pattern", confluence_count=confluence_count,
                           rsi=current_rsi, trend=current_trend, pattern=pattern, atr=current_atr)
            return None
        elif loss_match:
            logger.info(
                f"📝 [MTF] {tf}: Ostrzeżenie — wzorzec strat: {loss_match['pattern_type']} "
                f"({loss_match['count']}x) — kontynuuję ale z ostrzeżeniem"
            )
    except Exception as e:
        logger.debug(f"Loss pattern check skipped: {e}")

    # --- 6f. SESSION PERFORMANCE FILTER ---
    # Block trading in sessions where historical WR is poor for this direction
    try:
        current_session = analysis.get('session', 'unknown')
        session_perf = db.get_session_win_rate(current_session, direction_str, min_trades=5)
        if session_perf.get('sufficient_data') and session_perf['win_rate'] is not None:
            if session_perf['win_rate'] < 0.30:
                logger.info(
                    f"[MTF] {tf}: Session '{current_session}' WR={session_perf['win_rate']:.0%} "
                    f"for {direction_str} ({session_perf['count']} trades) — below 30%, pomijam"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"session_wr={session_perf['win_rate']:.0%}<30%({current_session})",
                               "session_performance",
                               confluence_count=confluence_count, rsi=current_rsi,
                               trend=current_trend, pattern=pattern, atr=current_atr)
                return None
            elif session_perf['win_rate'] < 0.40:
                logger.info(
                    f"[MTF] {tf}: Session '{current_session}' WR={session_perf['win_rate']:.0%} "
                    f"for {direction_str} — marginal, proceeding with caution"
                )
    except (AttributeError, TypeError) as e:
        logger.debug(f"Session performance check skipped: {e}")

    # --- 6g. HOURLY STATS CHECK ---
    try:
        from datetime import datetime
        current_hour = datetime.now().hour
        bad_hours = db.get_bad_hours(min_trades=5, max_winrate=0.35)
        for bh in bad_hours:
            hour, bh_dir, bh_wr, bh_count = bh
            if hour == current_hour and bh_dir == direction_str:
                logger.warning(
                    f"⏰ [MTF] {tf}: Godzina {current_hour}:00 ma winrate {bh_wr:.0%} "
                    f"dla {direction_str} ({bh_count} tradów) — pomijam"
                )
                _log_rejection(db, tf, direction_str, current_price,
                               f"bad_hour={current_hour}:00 WR={bh_wr:.0%}({bh_count}trades)",
                               "hourly_stats", confluence_count=confluence_count,
                               rsi=current_rsi, trend=current_trend, pattern=pattern, atr=current_atr)
                return None
    except Exception as e:
        logger.debug(f"Hourly stats check skipped: {e}")

    # --- 6g. HTF TREND CONFIRMATION (nie handluj przeciw wyższemu TF) ---
    # M5/M15 must align with H1; M15 should also check H4 for stronger confirmation
    htf_checks = []
    if tf == "5m":
        htf_checks = [("1h", "H1")]
    elif tf == "15m":
        htf_checks = [("1h", "H1"), ("4h", "H4")]
    elif tf == "1h":
        htf_checks = [("4h", "H4")]

    for htf_tf, htf_label in htf_checks:
        try:
            htf_analysis = get_smc_analysis(htf_tf)
            if htf_analysis:
                htf_trend = htf_analysis.get('trend', '')
                if direction == "LONG" and htf_trend == "bear":
                    logger.info(f"[MTF] {tf}: LONG ale {htf_label} trend=bear — NIE handluj przeciw HTF")
                    _log_rejection(db, tf, direction, current_price,
                                   f"htf_conflict:{htf_label}=bear", "htf_confirmation",
                                   confluence_count=confluence_count, rsi=current_rsi,
                                   trend=current_trend, pattern=pattern, atr=current_atr)
                    return None
                if direction == "SHORT" and htf_trend == "bull":
                    logger.info(f"[MTF] {tf}: SHORT ale {htf_label} trend=bull — NIE handluj przeciw HTF")
                    _log_rejection(db, tf, direction, current_price,
                                   f"htf_conflict:{htf_label}=bull", "htf_confirmation",
                                   confluence_count=confluence_count, rsi=current_rsi,
                                   trend=current_trend, pattern=pattern, atr=current_atr)
                    return None
        except (ImportError, AttributeError, TypeError) as e:
            logger.debug(f"[MTF] {htf_label} confirmation skipped: {e}")

    if htf_checks:
        logger.info(f"[MTF] {tf}: HTF trend alignment confirmed for {direction}")

    # --- 7. SETUP QUALITY SCORING (nowe!) ---
    setup_quality = None
    try:
        from src.trading.smc_engine import score_setup_quality
        setup_quality = score_setup_quality(analysis, direction)
        grade = setup_quality['grade']

        if grade == "C":
            logger.info(
                f"🔍 [MTF] {tf}: Setup grade=C ({setup_quality['score']}/100) — "
                f"zbyt niska jakość, pomijam"
            )
            _log_rejection(db, tf, direction, current_price,
                           f"setup_grade=C({setup_quality['score']}/100)", "setup_quality",
                           confluence_count=confluence_count, rsi=current_rsi,
                           trend=current_trend, pattern=pattern, atr=current_atr)
            return None

        logger.info(
            f"📊 [MTF] {tf}: Setup {grade} ({setup_quality['score']}/100) | "
            f"Risk mult: {setup_quality['risk_mult']} | R:R: {setup_quality['target_rr']}"
        )
    except Exception as e:
        logger.debug(f"Setup quality scoring skipped: {e}")
        setup_quality = {'grade': 'A', 'score': 50, 'risk_mult': 1.0, 'target_rr': 2.5, 'factors_detail': {}}

    # --- 8. SETUP WAŻNY — zwróć parametry trade'a ---
    grade_icon = {"A+": "⭐", "A": "✅", "B": "⚠️"}.get(setup_quality['grade'], "❓")
    logger.info(
        f"🎯 [MTF] ZNALEZIONO TRADE na {tf}! {grade_icon} Grade: {setup_quality['grade']} | "
        f"{direction} @ {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | {logic}"
    )

    # Extract SMC factors for self-learning attribution
    factors = extract_factors(analysis, direction)

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
        "factors": factors,
        "setup_quality": setup_quality,
        "ensemble_result": ensemble_result,
    }


def _get_adaptive_cooldown_hours(db) -> float:
    """
    Compute adaptive cooldown based on session + RECENT consecutive losses.

    2026-04-14: Halved base values across all sessions (scalp-friendly).
    The old 2.0h off_hours cooldown blocked legitimate post-NY-close
    setups on 5m. New base keeps meaningful rate-limiting but lets the
    scanner react to intraday setups without burning 2-3 hours between
    each one.

    Base cooldown per session:
      Asian:    0.75h  (was 1.5)
      London:   0.25h  (was 0.5 — high vol, fast moves)
      Overlap:  0.25h  (was 0.5 — max liquidity)
      NY:       0.5h   (was 0.75)
      Off-hours: 1.0h  (was 2.0 — thin liquidity but still tradeable)
      Weekend:  24.0h  (unchanged — no tradeable setups)

    Consecutive loss scaling: +0.3h per loss (up to +1h, was 2h).
    IMPORTANT: only losses within the last 24h count. Stale losses from
    earlier sessions (e.g. a 6-day-old loss streak) no longer keep the
    cooldown inflated forever.
    """
    # Session-dependent base cooldown
    try:
        from src.trading.smc_engine import get_active_session
        session_info = get_active_session()
        session = session_info.get('session', 'off_hours')
    except (ImportError, AttributeError):
        session = 'off_hours'

    base_hours = {
        'asian': 0.75,
        'london': 0.25,
        'overlap': 0.25,
        'new_york': 0.5,
        'off_hours': 1.0,
        'weekend': 24.0,
    }.get(session, 0.5)

    # Add penalty for consecutive RECENT losses (last 24h only).
    try:
        recent = db._query(
            "SELECT status FROM trades "
            "WHERE status IN ('WIN', 'LOSS') "
            "  AND timestamp >= datetime('now', '-24 hours') "
            "ORDER BY id DESC LIMIT 5"
        )
        consec_losses = 0
        for r in (recent or []):
            if r[0] == 'LOSS':
                consec_losses += 1
            else:
                break
        base_hours += min(consec_losses * 0.3, 1.0)
    except (AttributeError, TypeError, IndexError):
        pass

    return base_hours


def _check_trade_cooldown(db, min_hours: float = None) -> bool:
    """
    Sprawdza czy minął minimalny czas od ostatniego trade'a.
    Uses adaptive cooldown based on session + loss streak if min_hours not specified.
    Zwraca True jeśli można handlować, False jeśli jeszcze za wcześnie.
    """
    if min_hours is None:
        min_hours = _get_adaptive_cooldown_hours(db)

    try:
        from datetime import datetime, timedelta
        last_trade = db._query_one(
            "SELECT timestamp FROM trades ORDER BY id DESC LIMIT 1"
        )
        if last_trade and last_trade[0]:
            last_time = datetime.strptime(last_trade[0], "%Y-%m-%d %H:%M:%S")
            elapsed = (datetime.now() - last_time).total_seconds() / 3600
            if elapsed < min_hours:
                logger.info(
                    f"[COOLDOWN] Ostatni trade {elapsed:.1f}h temu, "
                    f"adaptive minimum {min_hours:.1f}h — pomijam"
                )
                return False
    except (ValueError, TypeError, AttributeError) as e:
        logger.debug(f"Cooldown check error: {e}")
    return True


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
    # --- RISK MANAGER: circuit breaker check before scanning ---
    try:
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        can_trade, reason = rm.check_circuit_breakers(balance)
        if not can_trade:
            logger.warning(f"[MTF] Risk manager blocked scan: {reason}")
            return None
    except (ImportError, AttributeError) as e:
        logger.debug(f"Risk manager unavailable: {e}")

    # --- COOLDOWN: minimum 30min między tradami (M5/M15 dają setupy częściej) ---
    if not _check_trade_cooldown(db):  # adaptive cooldown (session + loss streak)
        return None

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
        except (ImportError, AttributeError):
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
    - Metryki: scan_duration (timing), scan_errors_total (error rate)
    """
    from src.ops.metrics import scan_duration, scan_last_ts, TimerContext
    import time as _time
    scan_last_ts.set(_time.time())
    _scan_timer = TimerContext(scan_duration)
    _scan_timer.__enter__()
    try:
        # ── Weekend guard: rynek XAU/USD zamknięty pt 22:00 → nd 23:00 CET ──
        from src.trading.smc_engine import is_market_open
        if not is_market_open():
            logger.info("📅 [SCANNER] Rynek zamknięty (weekend) — pomijam skan")
            return

        # Prefetch all timeframes first (populates cache, reduces subsequent API calls)
        try:
            from src.data.data_sources import get_provider
            provider = get_provider()
            provider.prefetch_all_timeframes('XAU/USD')
        except Exception as e:
            logger.debug(f"Prefetch skipped: {e}")

        from src.core.database import NewsDB
        db = NewsDB()

        # Odczytaj balans portfela z bazy (jak robi _background_scanner w api/main.py)
        scan_balance = 10000.0
        scan_currency = "USD"
        try:
            bal = db.get_param("portfolio_balance")
            if bal and float(bal) > 0:
                scan_balance = float(bal)
            try:
                _curr = db.get_param("portfolio_currency_text")
                if _curr:
                    scan_currency = str(_curr)
            except (AttributeError, ValueError, TypeError):
                pass
        except (AttributeError, ValueError, TypeError):
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

            # Setup quality data
            setup_quality = trade_found.get('setup_quality', {})
            setup_grade = setup_quality.get('grade', 'A')
            setup_score = setup_quality.get('score', 50)

            # Deduplikacja — nie stawiaj tego samego trade'a dwa razy
            trade_key = _hash(f"mtf_{direction}_{entry:.3f}_{sl:.2f}_{tp:.2f}_{tf}")
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

                # Increment metrics
                try:
                    from src.ops.metrics import trades_opened
                    trades_opened.inc()
                except (ImportError, AttributeError):
                    pass

                # Zapisz setup grade + confirmation data + model agreement do trade'a
                try:
                    last_trade = db._query_one("SELECT id FROM trades ORDER BY id DESC LIMIT 1")
                    if last_trade:
                        trade_id = last_trade[0]
                        db.update_trade_setup_grade(trade_id, setup_grade, setup_score)

                        # Zapisz confirmation details + model agreement
                        import json as _json
                        # ensemble_result pochodzi z _evaluate_tf_for_trade (zachowany z get_ensemble_prediction)
                        ens_data = trade_found.get('ensemble_result')

                        if ens_data:
                            # Confirmation data
                            confirmation = ens_data.get('confirmation', {})
                            conf_json = _json.dumps(confirmation) if confirmation else None

                            # Model agreement
                            agreement_data = ens_data.get('model_agreement', {})
                            agreement_ratio = agreement_data.get('ratio', 0) if agreement_data else 0

                            # Volatility regime
                            vol_regime = "normal"
                            vol_pctile = ens_data.get('volatility_percentile', 0.5)
                            if vol_pctile < 0.25:
                                vol_regime = "low"
                            elif vol_pctile > 0.75:
                                vol_regime = "high"

                            db.update_trade_confirmation(trade_id, conf_json, agreement_ratio, vol_regime)

                            # Linkuj ostatnią ml_prediction z tym trade_id
                            db._execute(
                                "UPDATE ml_predictions SET trade_id = ? WHERE id = "
                                "(SELECT id FROM ml_predictions ORDER BY id DESC LIMIT 1)",
                                (trade_id,))
                        else:
                            db.update_trade_confirmation(trade_id, None, 0, "unknown")
                except Exception as e:
                    logger.warning(
                        f"[SCANNER] Trade {direction}@${entry:.2f} logged but "
                        f"setup_grade/confirmation update failed: {e}")

                logger.info(
                    f"💾 [SCANNER] Trade zapisany: {direction} @ {entry:.2f} "
                    f"| Grade: {setup_grade} ({setup_score}/100)"
                )

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

                # Wyślij alert Telegram z setup quality
                ml_line = f"\n🤖 {ml_info}" if ml_info else ""
                grade_icon = {"A+": "⭐", "A": "✅", "B": "⚠️"}.get(setup_grade, "❓")
                grade_line = f"\n{grade_icon} Setup: *{setup_grade}* ({setup_score}/100)"
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
                    f"💡 Logika: _{logic}_{ml_line}{grade_line}\n"
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
            from src.trading.finance import calculate_position
            try:
                _pos = calculate_position(analysis_base, 10000, "USD", TD_API_KEY)
                current_sl = _pos.get('sl', current_price)
                current_tp = _pos.get('tp', current_price)
            except (ValueError, TypeError, AttributeError, KeyError):
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
                    from src.trading.finance import calculate_position
                    hb_trend = hb_analysis['trend']
                    hb_price = hb_analysis['price']
                    hb_rsi = hb_analysis['rsi']
                    hb_structure = hb_analysis.get('structure', 'Stable')
                    direction_hb = "LONG" if hb_trend == "bull" else "SHORT"
                    try:
                        hb_pos = calculate_position(hb_analysis, 10000, "USD", TD_API_KEY)
                        hb_sl = hb_pos.get('sl', hb_price - 10)
                        hb_tp = hb_pos.get('tp', hb_price + 20)
                    except (ValueError, TypeError, AttributeError, KeyError):
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

        # Track signal rate: did this cycle produce a trade direction?
        try:
            from src.ops.metrics import (
                scan_signals_long, scan_signals_short, scan_signals_wait
            )
            if trade_found:
                _dir = (trade_found.get("direction") or "").upper()
                if "LONG" in _dir:
                    scan_signals_long.inc()
                elif "SHORT" in _dir:
                    scan_signals_short.inc()
                else:
                    scan_signals_wait.inc()
            else:
                scan_signals_wait.inc()
        except Exception:
            pass

    except Exception as e:
        try:
            from src.ops.metrics import scan_errors_total
            scan_errors_total.inc()
        except Exception:
            pass
        logger.error(f"❌ [SCANNER] Błąd: {e}")
    finally:
        _scan_timer.__exit__(None, None, None)


async def resolve_trades_task(context):
    """
    Resolver v2: Trailing Stop + Setup Quality Stats + Hourly Stats + Loss Classification.

    Trailing Stop Logic:
      ╔═══════════════════════════════════════════════════════╗
      ║  R-Multiple  │  Akcja                                ║
      ╠═══════════════════════════════════════════════════════╣
      ║  >= 1.0R     │  🔒 SL → Breakeven (entry)            ║
      ║  >= 1.5R     │  📈 SL → Entry + 1.0R (lock profit)   ║
      ║  >= 2.0R     │  🚀 SL → Entry + 1.5R (trail)         ║
      ╚═══════════════════════════════════════════════════════╝
    """
    from src.core.database import NewsDB
    db = NewsDB()

    # 1. POBIERANIE CENY
    try:
        from src.data.data_sources import get_provider
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
        open_trades = db.get_open_trades_extended()
        if not open_trades:
            return

        # Kontekst rynkowy (raz dla wszystkich)
        try:
            analysis = get_smc_analysis(USER_PREFS['tf'])
            market_snapshot = (
                f"Cena: {current_price} | "
                f"Trend: {analysis.get('trend', '?')} | "
                f"RSI: {analysis.get('rsi', '?')} | "
                f"Struktura: {analysis.get('structure', '?')} | "
                f"FVG: {analysis.get('fvg', '?')}"
            ) if analysis else f"Cena: {current_price}"
        except (TypeError, AttributeError, KeyError):
            market_snapshot = f"Cena: {current_price}"

        for trade in open_trades:
            t_id, direction, entry, sl, tp, trailing_sl, setup_grade, factors_json = trade
            status = None

            dir_clean = str(direction).strip().upper()
            entry_f = float(entry or 0)
            sl_f = float(trailing_sl or sl or 0)  # użyj trailing SL jeśli istnieje
            tp_f = float(tp or 0)
            original_sl = float(sl or 0)

            # ═══════════════════════════════════════════════════
            # TRAILING STOP LOGIC (5-level + ATR continuous trail)
            #
            # ╔═══════════════════════════════════════════════════════╗
            # ║  R-Multiple  │  Action                               ║
            # ╠═══════════════════════════════════════════════════════╣
            # ║  >= 0.5R     │  Reduce risk: SL → entry - 0.3R       ║
            # ║  >= 1.0R     │  Breakeven: SL → entry ± spread       ║
            # ║  >= 1.5R     │  Lock profit: SL → entry + 0.75R      ║
            # ║  >= 2.0R     │  Strong trail: SL → entry + 1.25R     ║
            # ║  >= 2.5R     │  ATR trail: SL → price - 1.5×ATR      ║
            # ╚═══════════════════════════════════════════════════════╝
            # ═══════════════════════════════════════════════════════
            sl_distance = abs(entry_f - original_sl) if entry_f and original_sl else 0

            if sl_distance > 0:
                if "LONG" in dir_clean:
                    r_multiple = (current_price - entry_f) / sl_distance
                else:
                    r_multiple = (entry_f - current_price) / sl_distance

                # Session-aware spread buffer for breakeven
                try:
                    from src.trading.risk_manager import get_risk_manager
                    spread_buf = get_risk_manager().get_spread_buffer()
                except (ImportError, AttributeError):
                    spread_buf = 0.60

                new_sl = sl_f  # default: no change
                trail_event = None
                candidate_sl = None

                # Helper: compute candidate SL for given lock level
                def _trail_sl(lock_r: float) -> float:
                    if "LONG" in dir_clean:
                        return round(entry_f + sl_distance * lock_r, 2)
                    else:
                        return round(entry_f - sl_distance * lock_r, 2)

                # Helper: check if candidate improves SL (LONG=higher, SHORT=lower)
                def _is_better(cand: float) -> bool:
                    if "LONG" in dir_clean:
                        return cand > sl_f
                    else:
                        return cand < sl_f

                if r_multiple >= 2.5:
                    # ATR-based continuous trailing — locks in most of the move
                    try:
                        _atr = analysis.get('atr', sl_distance) if analysis else sl_distance
                        atr_trail = max(_atr * 1.5, sl_distance * 0.5)  # min trail width = 0.5R
                        if "LONG" in dir_clean:
                            candidate_sl = round(current_price - atr_trail, 2)
                        else:
                            candidate_sl = round(current_price + atr_trail, 2)
                        # Don't let ATR trail go below the 2.0R lock level
                        fixed_floor = _trail_sl(1.25)
                        if "LONG" in dir_clean:
                            candidate_sl = max(candidate_sl, fixed_floor)
                        else:
                            candidate_sl = min(candidate_sl, fixed_floor)
                    except (TypeError, ValueError):
                        candidate_sl = _trail_sl(1.5)
                    trail_event = "ATR_TRAIL"

                elif r_multiple >= 2.0:
                    candidate_sl = _trail_sl(1.25)
                    trail_event = "TRAIL_2R"

                elif r_multiple >= 1.5:
                    candidate_sl = _trail_sl(0.75)
                    trail_event = "LOCK_1.5R"

                elif r_multiple >= 1.0:
                    # Breakeven — SL at entry ± spread buffer depending on side.
                    # BUG FIX 2026-04-14: SHORT branch was also using `+ spread_buf`,
                    # which moved the stop UP on a SHORT (i.e. AWAY from the
                    # already-in-profit price), defeating breakeven entirely.
                    if "LONG" in dir_clean:
                        candidate_sl = round(entry_f + spread_buf, 2)
                    else:
                        candidate_sl = round(entry_f - spread_buf, 2)
                    trail_event = "BREAKEVEN_1R"

                elif r_multiple >= 0.5:
                    # Partial risk reduction — cut initial risk by 30%.
                    # _trail_sl(r) returns entry_f + sl_dist * r where sl_dist is
                    # POSITIVE for LONG and NEGATIVE for SHORT. Passing -0.7
                    # correctly produces entry - 0.7R on LONG and entry + 0.7R
                    # on SHORT (both "pulling the SL closer to entry"), so this
                    # is actually direction-aware already. Left as-is after
                    # audit verification.
                    candidate_sl = _trail_sl(-0.7)
                    trail_event = "REDUCE_0.5R"

                # Apply trailing stop update (only if improvement)
                if candidate_sl is not None and trail_event and _is_better(candidate_sl):
                    new_sl = candidate_sl
                    db.update_trade_trailing_sl(t_id, new_sl)
                    db.log_trailing_stop_event(t_id, trail_event, sl_f, new_sl, current_price, round(r_multiple, 2))

                    locked_pnl = abs(new_sl - entry_f)
                    if "SHORT" in dir_clean:
                        locked_pnl = entry_f - new_sl if new_sl < entry_f else -(new_sl - entry_f)

                    logger.info(
                        f"[TRAILING] #{t_id} {dir_clean} | {trail_event} R={r_multiple:.1f} | "
                        f"SL: {sl_f:.2f} → {new_sl:.2f} | locked={locked_pnl:+.2f}$"
                    )

                    # Telegram alert on breakeven (milestone)
                    if trail_event == "BREAKEVEN_1R":
                        try:
                            send_telegram_alert(
                                f"*BREAKEVEN* #{t_id} {dir_clean}\n"
                                f"Entry: `{entry_f:.2f}$` | SL: `{new_sl:.2f}$`\n"
                                f"R: `{r_multiple:.1f}` | Ryzyko wyeliminowane"
                            )
                        except (AttributeError, TypeError, Exception) as e:
                            logger.debug(f"Breakeven alert failed: {e}")

                # Use updated SL for win/loss check
                sl_f = new_sl if new_sl != sl_f else sl_f

            # ═══════════════════════════════════════════════════
            # SPRAWDZENIE WIN/LOSS
            # ═══════════════════════════════════════════════════
            if "LONG" in dir_clean:
                if current_price >= tp_f:
                    status = "WIN"
                elif current_price <= sl_f:
                    status = "LOSS"
            elif "SHORT" in dir_clean:
                if current_price <= tp_f:
                    status = "WIN"
                elif current_price >= sl_f:
                    status = "LOSS"

            if status:
                # Oblicz profit/loss
                try:
                    if status == "WIN":
                        profit_val = round(abs(tp_f - entry_f), 2) if entry_f > 0 else 0
                    else:
                        # SL hit — compute actual P&L (trailing stop may yield positive P&L)
                        if "LONG" in dir_clean:
                            profit_val = round(sl_f - entry_f, 2)
                        else:
                            profit_val = round(entry_f - sl_f, 2)

                        # Trailing stop correction: if SL hit yields positive P&L, it's a WIN
                        if profit_val > 0:
                            status = "WIN"
                            logger.info(f"[RESOLVER] #{t_id} trailing stop hit with profit +{profit_val:.2f} → reclassified as WIN")
                except (ValueError, TypeError):
                    profit_val = 0

                db.update_trade_status(t_id, status)
                db.update_trade_profit(t_id, profit_val)

                # Audit trail + execution quality
                try:
                    from src.ops.compliance import log_audit_with_chain
                    log_audit_with_chain(t_id, "OPEN", status, "status", "OPEN", status,
                                        f"Price ${current_price:.2f}, profit ${profit_val:.2f}")
                    # Populate execution quality columns
                    db._execute(
                        "UPDATE trades SET filled_entry=entry, filled_sl=?, filled_tp=?, "
                        "slippage=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (sl_f, tp_f if status == "WIN" else None, t_id)
                    )
                except (AttributeError, TypeError):
                    pass

                # Metrics
                try:
                    from src.ops.metrics import trades_won, trades_lost
                    if status == "WIN":
                        trades_won.inc()
                    else:
                        trades_lost.inc()
                except (ImportError, AttributeError):
                    pass

                # Trade result Telegram alert
                try:
                    from src.ops.monitoring import alert_trade_result
                    alert_trade_result(t_id, dir_clean, status, entry_f, profit_val, setup_grade or "")
                except (ImportError, AttributeError):
                    pass

                # ═══════════════════════════════════════════════
                # AKTUALIZACJA STATYSTYK
                # ═══════════════════════════════════════════════

                # Session stats
                if status in ("WIN", "LOSS"):
                    row = db._query_one("SELECT pattern, session, timestamp FROM trades WHERE id = ?", (t_id,))
                    if row:
                        pattern = row[0] or "unknown"
                        session = row[1] or "Unknown"
                        db.update_session_stats(pattern, session, status)

                        # Hourly stats (nowe!)
                        try:
                            ts = row[2]
                            if ts:
                                hour = int(ts[11:13])
                                db.update_hourly_stats(hour, dir_clean, status)
                        except (ValueError, TypeError, IndexError):
                            pass

                    # Setup quality stats (nowe!)
                    if setup_grade:
                        db.update_setup_quality_stats(setup_grade, dir_clean, status, profit_val)

                # Factor weights + ensemble weights
                if status in ("WIN", "LOSS"):
                    from src.learning.self_learning import update_factor_weights
                    update_factor_weights(t_id, status)

                    # A/B testing: record outcome
                    try:
                        from src.learning.ab_testing import get_ab_manager
                        ab = get_ab_manager()
                        if ab.is_active:
                            ab.record_outcome(status)
                    except (ImportError, AttributeError):
                        pass

                    # Loss classification (nowe!)
                    if status == "LOSS":
                        try:
                            from src.learning.self_learning import classify_loss
                            classify_loss(t_id)
                        except Exception as e:
                            logger.debug(f"Loss classification skipped: {e}")

                    # Ensemble weights
                    try:
                        from src.ml.ensemble_models import update_ensemble_weights
                        factors = db.get_trade_factors(t_id)
                        correct = []
                        incorrect = []

                        if status == "WIN":
                            correct.append("smc")
                        else:
                            incorrect.append("smc")

                        ml_factors_bull = any(factors.get(k) for k in ('ichimoku_bull', 'ml_ensemble_long'))
                        ml_factors_bear = any(factors.get(k) for k in ('ichimoku_bear', 'ml_ensemble_short'))

                        has_ml_signal = ml_factors_bull or ml_factors_bear
                        if has_ml_signal:
                            ml_agreed_with_direction = (
                                (ml_factors_bull and "LONG" in dir_clean) or
                                (ml_factors_bear and "SHORT" in dir_clean)
                            )
                            if status == "WIN" and ml_agreed_with_direction:
                                correct.extend(["lstm", "xgb"])
                            elif status == "LOSS" and ml_agreed_with_direction:
                                incorrect.extend(["lstm", "xgb"])
                            elif status == "WIN" and not ml_agreed_with_direction:
                                incorrect.extend(["lstm", "xgb"])

                        if correct or incorrect:
                            update_ensemble_weights(correct, incorrect)
                    except Exception as e:
                        logger.debug(f"Ensemble weight update skipped: {e}")

                    # Regime stats
                    try:
                        trow = db._query_one(
                            "SELECT session, factors FROM trades WHERE id = ?", (t_id,)
                        )
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

                # Pattern weight
                pattern_row = db._query_one("SELECT pattern FROM trades WHERE id = ?", (t_id,))
                pattern = pattern_row[0] if pattern_row else None
                analysis_data = {"pattern": pattern}
                from src.learning.self_learning import update_pattern_weight
                update_pattern_weight(analysis_data, status)

                # ═══════════════════════════════════════════════
                # FILTER PERFORMANCE TRACKING
                # ═══════════════════════════════════════════════
                # Po rozwiązaniu trade'a: zaktualizuj accuracy filtrów
                # które przepuściły ten trade (blocked=False)
                try:
                    import json as _jfp
                    conf_row = db._query_one(
                        "SELECT confirmation_data FROM trades WHERE id = ?", (t_id,))
                    if conf_row and conf_row[0]:
                        conf_data = _jfp.loads(conf_row[0])
                        adjustments = conf_data.get('adjustments', {})
                        trade_won = status == "WIN"
                        # Każdy filtr który przepuścił ten trade
                        for filter_name, mult_value in adjustments.items():
                            db.update_filter_performance(
                                filter_name, dir_clean,
                                blocked=False, trade_won=trade_won)
                except Exception as e:
                    logger.debug(f"Filter performance update skipped: {e}")

                # Walidacja ostatnich odrzuceń — sprawdź czy odrzucone setupy
                # faktycznie by przegrały (na podstawie ceny po odrzuceniu)
                try:
                    recent_rejections = db._query("""
                        SELECT id, direction, price, filter_name
                        FROM rejected_setups
                        WHERE would_have_won IS NULL
                        AND timestamp > datetime('now', '-24 hours')
                        LIMIT 20
                    """)
                    for rej in recent_rejections:
                        rej_id, rej_dir, rej_price, rej_filter = rej
                        if rej_price and current_price:
                            rej_price_f = float(rej_price)
                            # Prosty heurystyka: jeśli cena poszła w kierunku trade'a o > 0.3%
                            # to odrzucenie było złe (trade by wygrał)
                            price_change_pct = (current_price - rej_price_f) / rej_price_f
                            if rej_dir == "LONG":
                                would_win = price_change_pct > 0.003  # >0.3% w górę
                            else:
                                would_win = price_change_pct < -0.003  # >0.3% w dół
                            db.validate_rejection(rej_id, would_win)
                            if rej_filter:
                                db.update_filter_performance(
                                    rej_filter, rej_dir,
                                    blocked=True, trade_won=would_win)
                except Exception as e:
                    logger.debug(f"Rejection validation skipped: {e}")

                exit_price = float(tp) if status == "WIN" else sl_f

                # Loss details
                if status == "LOSS":
                    reason = (
                        f"Cena dotknęła SL ({sl_f:.2f}$). "
                        f"Wejście było na {entry_f:.2f}$, "
                        f"kierunek: {direction}."
                    )
                    if trailing_sl and float(trailing_sl) != original_sl:
                        reason += f" [Trailing SL aktywny: original SL={original_sl:.2f}$]"
                    db.log_loss_details(
                        trade_id=t_id,
                        reason=reason,
                        market_condition=market_snapshot
                    )
                    logger.info(f"📝 [RESOLVER] Zapisano okoliczności straty dla pozycji {t_id}.")

                # ═══════════════════════════════════════════════
                # POWIADOMIENIE
                # ═══════════════════════════════════════════════
                icon = "✅" if status == "WIN" else "❌"
                profit_icon = "💰" if profit_val > 0 else "📉"
                trailing_info = ""
                if trailing_sl and float(trailing_sl or 0) != original_sl:
                    trailing_events = db.get_trailing_stop_history(t_id)
                    if trailing_events:
                        trail_summary = " → ".join([f"{e[1]}" for e in trailing_events])
                        trailing_info = f"\n📊 Trailing: {trail_summary}"

                grade_info = f" | Grade: {setup_grade}" if setup_grade else ""
                msg = (
                    f"{icon} *POZYCJA ROZSTRZYGNIĘTA!*\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"ID: `{t_id}` | Kierunek: {direction}{grade_info}\n"
                    f"Wynik: *{status}* {profit_icon} `{profit_val:+.2f}$`\n"
                    f"Wejście: `{entry_f:.2f}$` | Wyjście: `{exit_price:.2f}$`"
                    f"{trailing_info}"
                )
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                logger.info(f"💰 [RESOLVER] Zamknięto pozycję {t_id} jako {status} ({profit_val:+.2f}$)")

    except Exception as e:
        logger.error(f"🚨 [RESOLVER] Błąd podczas sprawdzania pozycji: {e}")
