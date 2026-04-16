# finance.py
"""
finance.py — obliczenia finansowe i zarządzanie ryzykiem.

Zmiany:
- Stały minimalny dystans TP = 5$.
- Dodano dynamiczny filtr: min_tp_distance = max(atr * min_tp_distance_mult, 5.0).
- Parametr min_tp_distance_mult jest przechowywany w dynamic_params i może być optymalizowany.
- Kurs walutowy pobierany przez DataProvider (nie bezpośrednie requesty).
"""

from src.core.logger import logger


def _bump_metric(name: str) -> None:
    """Safely increment a metrics counter. Failures are swallowed — metrics
    must never break the trading path. `name` is the attribute on src.ops.metrics."""
    try:
        from src.ops import metrics as _m
        counter = getattr(_m, name, None)
        if counter is not None:
            counter.inc()
    except Exception:
        pass


def get_fx_rate(base: str = "USD", target: str = "PLN") -> float:
    """Pobiera kurs walutowy (fallback 4.0)."""
    try:
        import yfinance as yf
        symbol = f"{base}{target}=X"
        data = yf.Ticker(symbol).history(period="1d")
        if not data.empty:
            return round(float(data['Close'].iloc[-1]), 4)
        return 4.00
    except Exception:
        return 4.00


def calculate_position(analysis_data: dict, balance: float, user_currency: str,
                       td_api_key: str = "", df=None) -> dict:
    """
    SMC MASTER VERSION: Oblicza pozycję w oparciu o Liquidity Grab, MSS, FVG, DBR/RBD, makro i ALL ML MODELS.

    Note: `td_api_key` is DEPRECATED and unused (FX rate fetch uses yfinance).
    Kept in signature for backward compat with existing callers.

    Integruje:
    - SMC Engine (trend, struktura, FVG)
    - LSTM Model (predykcja kierunku)
    - XGBoost Model (predykcja kierunku)
    - DQN Agent (rekomendacja akcji)
    - Ensemble Voting (fuzja wszystkich modeli)

    Filtry:
    - Minimalny dystans TP = 5$ (stały) lub dynamiczny = atr * min_tp_distance_mult (jeśli większy).
    - Filtr pewności ensemble (confidence < 40% = CZEKAJ)
    """
    # Dane z silnika SMC
    price = analysis_data['price']
    trend = analysis_data['trend']
    fvg_type = analysis_data.get('fvg_type')
    fvg_upper = analysis_data.get('fvg_upper')
    fvg_lower = analysis_data.get('fvg_lower')
    ob_price = analysis_data.get('ob_price', price)
    grab = analysis_data.get('liquidity_grab', False)
    grab_dir = analysis_data.get('liquidity_grab_dir')
    mss = analysis_data.get('mss', False)
    macro_regime = analysis_data.get('macro_regime', 'neutralny')
    dbr_rbd_type = analysis_data.get('dbr_rbd_type')
    base_low = analysis_data.get('dbr_rbd_base_low')
    base_high = analysis_data.get('dbr_rbd_base_high')
    swing_high = analysis_data.get('swing_high')
    swing_low = analysis_data.get('swing_low')
    atr = analysis_data.get('atr', 2.0)

    # Session awareness — widen SL during killzones, skip off-hours
    session = analysis_data.get('session', 'unknown')
    is_killzone = analysis_data.get('is_killzone', False)
    sl_multiplier = 1.3 if is_killzone else 1.0  # Killzone = wyższa zmienność → szerszy SL

    # --- FILTR SESJI: sesja azjatycka dla slow TFs blokowana (za dużo noise
    # vs sygnał dla SL $5+), ale 5m/15m scalp (SL $2-3) radzi sobie z chop.
    # Zmiana 2026-04-15: pozwolono 5m/15m w Azji bo user widział sporo ruchów
    # których silnik nie łapał przez ten filtr. H4/H1 nadal blokowane.
    _tf_raw = (analysis_data.get('tf') or '').lower()
    _is_slow_tf = _tf_raw in ('4h', '1h', '60m', 'h4', 'h1')
    if session == 'asian' and _is_slow_tf:
        _bump_metric("trades_rejected")
        return {"direction": "CZEKAJ", "reason": "Sesja azjatycka — slow TF (H4/H1) za dużo noise na XAU/USD"}

    # Pobranie dynamicznych parametrów (zamiast hardcoded)
    from src.core.database import NewsDB
    db = NewsDB()

    # --- RISK MANAGER: Kelly sizing + circuit breakers ---
    from src.trading.risk_manager import get_risk_manager, MAX_PORTFOLIO_HEAT_PCT
    rm = get_risk_manager()

    # Check circuit breakers before anything else
    can_trade, reason = rm.check_circuit_breakers(balance)
    if not can_trade:
        _bump_metric("trades_blocked_by_risk")
        return {"direction": "CZEKAJ", "reason": f"Risk manager: {reason}"}

    # Use Kelly-optimal risk instead of fixed 1%
    default_risk = float(db.get_param("risk_percent", 1.0))
    risk_percent = rm.compute_kelly_risk_percent(default_risk)

    # Apply daily drawdown multiplier (reduces risk as daily losses accumulate)
    daily_mult = rm.get_daily_risk_multiplier(balance)
    if daily_mult < 1.0:
        logger.info(f"Daily risk reduction active: {daily_mult:.0%} of normal risk")
        risk_percent *= daily_mult

    min_tp_distance_mult = db.get_param("min_tp_distance_mult", 1.0)
    sl_atr_mult = db.get_param("sl_atr_multiplier", 1.5)
    sl_min_distance = db.get_param("sl_min_distance", 4.0)
    tp_to_sl_ratio = db.get_param("tp_to_sl_ratio", 2.5)

    # Scalp mode: 5m TFs get tighter floors so $10-30 moves can clear filters.
    # On H1+ we keep the original conservative floors (4.0 SL, 2.5 RR).
    # Rationale: XAU/USD on 5m has ATR ~$2-4, so forcing $4 SL + 2.5 RR means
    # $10 min TP and swing-based targets usually blow up to $30-80. Scalp mode
    # relaxes to $2 SL floor + 1.5 RR + TP capped at 3R (kills lottery ticket
    # swing-based TPs while keeping the realistic scalp range on the table).
    tf_signal = (analysis_data.get('tf') or '').lower()
    is_scalp = tf_signal in ('5m', '5min', 'm5')
    # Low-TF scalp window: covers 5m/15m/30m for filter decisions (macro
    # soft-halve, ML conf threshold 0.3). Keeps strict SL/RR floors
    # reserved for `is_scalp` (5m only) because 15m/30m ATR is larger
    # and needs wider stops from structure.
    is_low_tf_scalp = tf_signal in ('5m', '5min', 'm5', '15m', '15min', 'm15', '30m', '30min', 'm30')
    # Tracks soft-block conditions that halve risk instead of blocking.
    # Used for against-macro scalps on low TFs — classic intraday trade
    # against slow macro bias is fine if we cut size.
    scalp_risk_halve = False
    if is_scalp:
        sl_floor = 2.0
        rr_floor = 1.5
        target_rr_cap = 3.0  # max TP distance as multiple of SL distance
    else:
        sl_floor = sl_min_distance
        rr_floor = 2.0
        target_rr_cap = None  # no cap — honor structural swing/FVG targets

    # ========== 🤖 ENSEMBLE ML INTEGRATION ==========
    ensemble_result = None
    ml_signal = None

    # Pobierz live data z Twelve Data jeśli nie podany df
    if df is None:
        try:
            from src.data.data_sources import get_provider
            provider = get_provider()
            logger.debug("📡 Fetching live candles from Twelve Data for ML analysis")
            df = provider.get_candles('XAU/USD', '15m', 200)
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch live data: {e}")
            df = None

    if df is not None and not df.empty:
        try:
            from src.ml.ensemble_models import get_ensemble_prediction
            initial_balance = balance  # Założenie, że balance to obecny stan
            # Fetch current position from database (0=flat, 1=long, -1=short)
            current_position = 0
            try:
                open_trades = db.get_open_trades()
                if open_trades:
                    last_dir = str(open_trades[-1][1]).upper()
                    current_position = 1 if "LONG" in last_dir else -1
            except (AttributeError, IndexError, TypeError):
                pass
            ensemble_result = get_ensemble_prediction(
                df=df,
                smc_trend=trend,
                current_price=price,
                balance=balance,
                initial_balance=initial_balance,
                position=current_position,
                use_twelve_data=False  # Już mamy df, nie pobieraj ponownie
            )
            ml_signal = ensemble_result.get('ensemble_signal', 'CZEKAJ')
            logger.info(f"🤖 ML Ensemble Signal: {ml_signal} (confidence: {ensemble_result.get('confidence', 0):.1%})")
        except Exception as e:
            logger.warning(f"⚠️ Ensemble error: {e}")
            ensemble_result = None
    else:
        logger.debug("⚠️ No data for ML analysis, skipping ensemble")

    # --- 1. Ustal kierunek na podstawie konfluencji + ML ---
    direction = None
    entry = price
    logic = ""

    if grab and mss:
        if grab_dir == "bullish":
            direction = "LONG"
            entry = ob_price if ob_price > price else price
            logic = "Liquidity Grab + MSS (Bullish)"
        elif grab_dir == "bearish":
            direction = "SHORT"
            # For SHORT: OB is resistance (high) — enter at or near OB above price
            entry = ob_price if ob_price and ob_price > price * 0.995 else price
            logic = "Liquidity Grab + MSS (Bearish)"
    elif dbr_rbd_type == "DBR":
        direction = "LONG"
        entry = base_high if base_high else price
        logic = "DBR (Drop-Base-Rally)"
    elif dbr_rbd_type == "RBD":
        direction = "SHORT"
        # RBD: enter at top of base (resistance) — sell the rally
        entry = base_high if base_high else price
        logic = "RBD (Rally-Base-Drop)"
    else:
        if trend == "bull":
            direction = "LONG"
            logic = "Trend Bull + FVG"
        else:
            direction = "SHORT"
            logic = "Trend Bear + FVG"

    # ========== ML VALIDATION: Weryfikuj SMC sygnał przez ensemble ==========
    if ensemble_result and ml_signal != "CZEKAJ":
        smc_bullish = direction == "LONG"
        ml_bullish = ml_signal == "LONG"

        if smc_bullish == ml_bullish:
            # SMC i ML się zgadzają - dodaj confidence boost
            logic += f" [ML: {ensemble_result.get('confidence', 0):.0%}✅]"
        else:
            # SMC i ML się NIE zgadzają
            logger.warning(f"⚠️ SMC ({direction}) vs ML ({ml_signal}) KONFLIKT (confidence: {ensemble_result.get('confidence', 0):.0%})")
            logic += f" [ML: {ensemble_result.get('confidence', 0):.0%}⚠️]"

            # BLOKADA: Jeśli ML ma wysoką pewność i mówi inaczej niż SMC — nie otwieraj trade'a
            # Scalp mode: raise conflict threshold from 55% → 65% (ML needs very
            # high conviction to veto a scalp; small SL limits downside anyway).
            conflict_threshold = 0.65 if is_scalp else 0.55
            if ensemble_result.get('confidence', 0) > conflict_threshold:
                _bump_metric("trades_rejected")
                return {
                    "direction": "CZEKAJ",
                    "reason": f"ML ({ml_signal}, {ensemble_result.get('confidence', 0):.0%}) konflikt z SMC ({direction}) — czekamy",
                    "ensemble_data": ensemble_result
                }

    # Filtrowanie makro
    if macro_regime == "czerwony" and direction == "LONG":
        if is_low_tf_scalp:
            logger.warning(f"🟡 [SCALP] Makro czerwony vs LONG on {tf_signal} — halve risk (not block)")
            scalp_risk_halve = True
        else:
            _bump_metric("trades_rejected")
            return {"direction": "CZEKAJ", "reason": "Makro czerwony – przeciwwskazanie do LONG"}
    if macro_regime == "zielony" and direction == "SHORT":
        if is_low_tf_scalp:
            logger.warning(f"🟡 [SCALP] Makro zielony vs SHORT on {tf_signal} — halve risk (not block)")
            scalp_risk_halve = True
        else:
            _bump_metric("trades_rejected")
            return {"direction": "CZEKAJ", "reason": "Makro zielony – przeciwwskazanie do SHORT"}

    # ========== FILTR PEWNOŚCI ENSEMBLE ==========
    # Low-TF scalp: lower min confidence 0.4 → 0.3 so borderline signals on
    # 5m/15m/30m don't get culled just because ensemble is uncertain (scalp
    # is inherently noisier than swing setups).
    min_conf_threshold = 0.3 if is_low_tf_scalp else 0.4
    if ensemble_result and ensemble_result.get('confidence', 0) < min_conf_threshold and ml_signal == "CZEKAJ":
        _bump_metric("trades_rejected")
        return {
            "direction": "CZEKAJ",
            "reason": f"Niska pewność ensemble ({ensemble_result.get('confidence', 0):.1%}) - czekamy na wyraźniejszy sygnał",
            "ensemble_data": ensemble_result
        }

    # --- 1b. SETUP QUALITY SCORING ---
    setup_quality = None
    try:
        from src.trading.smc_engine import score_setup_quality
        setup_quality = score_setup_quality(analysis_data, direction)
        grade = setup_quality['grade']
        logger.info(
            f"📊 Setup Quality: {grade} ({setup_quality['score']}/100) | "
            f"Factors: {list(setup_quality['factors_detail'].keys())}"
        )

        # Grade C = zbyt słaby setup → nie handluj
        if grade == "C":
            return {
                "direction": "CZEKAJ",
                "reason": f"Setup quality zbyt niski: {grade} ({setup_quality['score']}/100)",
                "setup_quality": setup_quality
            }

        # Dynamiczny R:R i risk na podstawie grade
        if grade == "A+":
            tp_to_sl_ratio = max(tp_to_sl_ratio, 3.0)
            risk_percent = min(risk_percent * 1.5, 2.0)  # max 2%
        elif grade == "A":
            tp_to_sl_ratio = max(tp_to_sl_ratio, 2.5)
            # risk_percent bez zmian (default)
        elif grade == "B":
            tp_to_sl_ratio = max(tp_to_sl_ratio, 2.0)
            risk_percent = risk_percent * 0.7  # zmniejszone ryzyko

        logger.info(f"📊 Adjusted: R:R={tp_to_sl_ratio}, Risk={risk_percent:.2f}%")
    except Exception as e:
        logger.debug(f"Setup quality scoring skipped: {e}")

    # --- Consecutive loss protection ---
    try:
        recent_trades = db._query(
            "SELECT status FROM trades WHERE status IN ('WIN', 'LOSS') ORDER BY id DESC LIMIT 3"
        )
        consecutive_losses = 0
        for t in recent_trades:
            if t[0] == 'LOSS':
                consecutive_losses += 1
            else:
                break
        if consecutive_losses >= 2:
            risk_percent *= 0.75  # 25% reduction after 2 consecutive losses
            logger.info(f"⚠️ {consecutive_losses} strat z rzędu → risk zmniejszony do {risk_percent:.2f}%")
    except (IndexError, TypeError, ValueError, AttributeError):
        pass

    # --- 2. SL i TP (STRUCTURAL PLACEMENT) ---
    # SL based on market structure (swing levels), not ATR from entry.
    # Scalp mode (5m): sl_floor = 2.0, rr_floor = 1.5, TP capped at 3R.
    # Swing mode (H1+): sl_floor = DB config (default 4.0), rr_floor = 2.0, no cap.
    sl_min = sl_floor
    sl_max = max(atr * 4.0, 30.0)      # absolute max $30 (or 4x ATR)

    if direction == "LONG":
        # SL: ponizej swing low (strukturalny poziom) + bufor ATR
        if swing_low and swing_low < entry:
            sl = round(swing_low - atr * 0.3 * sl_multiplier, 2)
        elif ob_price and ob_price < entry:
            sl = round(ob_price - atr * 0.3 * sl_multiplier, 2)
        else:
            sl = round(entry - atr * sl_atr_mult * sl_multiplier, 2)

        # Clamp SL distance to min/max range
        sl_dist = entry - sl
        if sl_dist < sl_min:
            sl = round(entry - sl_min, 2)
            sl_dist = sl_min
        elif sl_dist > sl_max:
            sl = round(entry - sl_max, 2)
            sl_dist = sl_max

        # TP: strukturalny target z wymuszonym minimum R:R
        min_rr = max(tp_to_sl_ratio, rr_floor)
        tp_min_target = entry + sl_dist * min_rr
        # Scalp mode: cap TP at target_rr_cap × SL distance so swing/FVG
        # targets don't push us into "wait for $80 move" territory.
        tp_cap = entry + sl_dist * target_rr_cap if target_rr_cap else None

        if swing_high and swing_high > tp_min_target:
            tp = round(min(swing_high, tp_cap) if tp_cap else swing_high, 2)
        elif fvg_type == "bullish" and fvg_upper and fvg_upper > tp_min_target:
            tp = round(min(fvg_upper, tp_cap) if tp_cap else fvg_upper, 2)
        else:
            tp = round(tp_min_target, 2)

        # Validate R:R >= rr_floor
        actual_rr = (tp - entry) / (entry - sl) if (entry - sl) > 0 else 0
        if actual_rr < rr_floor:
            tp = round(entry + sl_dist * rr_floor, 2)

    else:  # SHORT
        # SL: powyzej swing high (strukturalny poziom) + bufor ATR
        if swing_high and swing_high > entry:
            sl = round(swing_high + atr * 0.3 * sl_multiplier, 2)
        elif ob_price and ob_price > entry:
            sl = round(ob_price + atr * 0.3 * sl_multiplier, 2)
        else:
            sl = round(entry + atr * sl_atr_mult * sl_multiplier, 2)

        # Clamp SL distance
        sl_dist = sl - entry
        if sl_dist < sl_min:
            sl = round(entry + sl_min, 2)
            sl_dist = sl_min
        elif sl_dist > sl_max:
            sl = round(entry + sl_max, 2)
            sl_dist = sl_max

        # TP: strukturalny target z minimum R:R
        min_rr = max(tp_to_sl_ratio, rr_floor)
        tp_min_target = entry - sl_dist * min_rr
        # Scalp mode: cap TP distance at target_rr_cap × SL distance.
        tp_cap = entry - sl_dist * target_rr_cap if target_rr_cap else None

        if swing_low and swing_low < tp_min_target:
            tp = round(max(swing_low, tp_cap) if tp_cap else swing_low, 2)
        elif fvg_type == "bearish" and fvg_lower and fvg_lower < tp_min_target:
            tp = round(max(fvg_lower, tp_cap) if tp_cap else fvg_lower, 2)
        else:
            tp = round(tp_min_target, 2)

        # Validate R:R >= rr_floor
        actual_rr = (entry - tp) / (sl - entry) if (sl - entry) > 0 else 0
        if actual_rr < rr_floor:
            tp = round(entry - sl_dist * rr_floor, 2)

    # --- 3. Waluta i kapitał ---
    balance_in_usd = balance
    if user_currency != "USD":
        try:
            from src.data.data_sources import get_provider
            provider = get_provider()
            rate = provider.get_exchange_rate("USD", user_currency)
            if rate is None:
                rate = 4.0
            balance_in_usd = balance / rate
        except (ImportError, AttributeError, TypeError, ValueError):
            balance_in_usd = balance / 4.0

    # --- 4. Slippage adjustment (session + volatility-aware spread) ---
    spread_buffer = rm.get_spread_buffer(atr=atr)
    entry, sl, tp = rm.adjust_for_slippage(entry, sl, tp, direction, atr=atr)

    # --- 5. Wielkość lota (ryzyko % + volatility targeting) ---
    # Volatility-adjusted sizing: większe pozycje w spokojnych okresach,
    # mniejsze w wysokiej volatilności (utrzymuje stałą $ volatility portfela)
    vol_mult = rm.compute_volatility_multiplier(atr)
    if abs(vol_mult - 1.0) > 0.05:
        logger.info(f"📊 Volatility adjustment: {vol_mult:.2f}x (ATR={atr:.2f})")
        risk_percent_adj = risk_percent * vol_mult
    else:
        risk_percent_adj = risk_percent

    risk_usd = balance_in_usd * (risk_percent_adj / 100)
    dist = abs(entry - sl)
    if dist <= 0:
        dist = 2.0
    lot_size = round(risk_usd / (dist * 100), 2)
    if lot_size < 0.01:
        lot_size = 0.01
    # Hard upper bound — protect against pathological inputs (tiny dist,
    # huge balance, bad risk_percent) that could ask for 30+ lots (= $3M
    # notional on XAU/USD). 0.5 lot = ~$50k notional, well within typical
    # broker micro limits and consistent with conservative risk profile.
    if lot_size > 0.5:
        logger.warning(
            f"lot_size {lot_size} exceeds safety cap — clamped to 0.5 "
            f"(risk_usd={risk_usd:.2f} dist={dist:.2f} balance={balance_in_usd:.2f})")
        lot_size = 0.5

    # Scalp soft-block risk halving — against-macro 5m scalps take half size.
    # Also honors structure_conflict flag set by scanner (direction_conflict
    # soft-block on 5m). One flag, one halving regardless of source.
    if scalp_risk_halve or analysis_data.get('_scalp_risk_halve'):
        original_lot = lot_size
        lot_size = round(lot_size * 0.5, 2)
        if lot_size < 0.01:
            lot_size = 0.01
        logger.info(f"[SCALP] Risk halved: {original_lot} → {lot_size} lot")

    # --- 6. Portfolio heat check (max aggregate risk) ---
    can_open, heat_pct = rm.check_portfolio_heat(balance_in_usd, risk_usd)
    if not can_open:
        _bump_metric("trades_blocked_by_risk")
        return {"direction": "CZEKAJ",
                "reason": f"Portfolio heat {heat_pct:.1f}% exceeds {MAX_PORTFOLIO_HEAT_PCT}% limit"}

    # --- 7. FILTR: minimalny dystans TP ---
    # Scalp mode: $3 floor so 5m setups with SL=$2 + RR=1.5 ($3 TP) aren't
    # rejected. Swing mode: $5 floor as before.
    MIN_TP_DISTANCE = 3.0 if is_scalp else 5.0
    dynamic_min_distance = atr * min_tp_distance_mult
    min_distance = max(dynamic_min_distance, MIN_TP_DISTANCE)

    if abs(entry - tp) < min_distance:
        _bump_metric("trades_rejected")
        return {"direction": "CZEKAJ",
                "reason": f"Zbyt mały dystans TP ({abs(entry - tp):.2f}$) – minimalny {min_distance:.2f}$."}

    result = {
        'lot': lot_size,
        'sl': sl,
        'tp': tp,
        'entry': entry,
        'direction': direction,
        'logic': logic,
    }

    # Dodaj setup quality data jeśli dostępna
    if setup_quality:
        result['setup_quality'] = setup_quality

    # Dodaj ML ensemble data jeśli dostępna
    if ensemble_result:
        result['ensemble_data'] = {
            'signal': ensemble_result.get('ensemble_signal', 'CZEKAJ'),
            'final_score': round(ensemble_result.get('final_score', 0), 3),
            'confidence': round(ensemble_result.get('confidence', 0), 2),
            'models_available': ensemble_result.get('models_available', 0),
            'predictions': {
                k: {
                    'direction': v.get('direction'),
                    'confidence': round(v.get('confidence', 0), 2),
                    'status': v.get('status', 'ok')
                } for k, v in ensemble_result.get('predictions', {}).items()
            }
        }

    return result
