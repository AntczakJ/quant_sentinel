# finance.py
"""
finance.py — obliczenia finansowe i zarządzanie ryzykiem.

Zmiany:
- Stały minimalny dystans TP = 5$.
- Dodano dynamiczny filtr: min_tp_distance = max(atr * min_tp_distance_mult, 5.0).
- Parametr min_tp_distance_mult jest przechowywany w dynamic_params i może być optymalizowany.
"""

import os

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


def calculate_position(analysis_data: dict, balance: float, user_currency: str,
                       td_api_key: str = "", df=None) -> dict:
    """
    SMC MASTER VERSION: Oblicza pozycję w oparciu o Liquidity Grab, MSS, FVG, DBR/RBD, makro i ALL ML MODELS.

    Note: `td_api_key` is DEPRECATED and unused. Kept in signature for
    backward compat with existing callers.

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

    # Session-based risk multiplier (2026-04-16): thin liquidity sessions
    # see wider spreads, slower move development, higher slippage. Cut
    # risk accordingly so a bad fill doesn't become a bad trade.
    #   overlap (London+NY): 1.0x — max liquidity window
    #   london:              1.0x
    #   new_york:            1.0x
    #   asian:               0.6x — narrow range, breakout-heavy failures
    #   off_hours:           0.5x — post-NY close, lowest vol
    #   weekend:             0.0x — shouldn't trade at all, belt+braces
    try:
        _session = (analysis_data.get('session') or 'off_hours').lower()
        _session_mult = {
            'overlap': 1.0, 'london': 1.0, 'new_york': 1.0,
            'asian': 0.6, 'off_hours': 0.5, 'weekend': 0.0,
        }.get(_session, 0.75)
        if _session_mult < 1.0:
            logger.info(f"Session risk scaling: {_session}={_session_mult:.0%}")
            risk_percent *= _session_mult
    except Exception:
        pass

    min_tp_distance_mult = db.get_param("min_tp_distance_mult", 1.0)
    sl_atr_mult = db.get_param("sl_atr_multiplier", 1.5)
    sl_min_distance = db.get_param("sl_min_distance", 4.0)
    tp_to_sl_ratio = db.get_param("tp_to_sl_ratio", 2.5)

    # Scalp mode: 5m TFs get tighter floors so $10-30 moves can clear filters.
    # On H1+ we keep the original conservative floors (4.0 SL, 2.5 RR).
    # Rationale: XAU/USD on 5m has ATR ~$2-4, so forcing $4 SL + 2.5 RR means
    # $10 min TP and swing-based targets usually blow up to $30-80. Scalp mode
    # relaxes to $4 SL floor + 1.5 RR + TP capped at 3R (kills lottery ticket
    # swing-based TPs while keeping the realistic scalp range on the table).
    # SL floor raised from 2.0 → 4.0 on 2026-04-19: historical review showed
    # 8/8 trades at SL<=2.0 were losses (spread-trade pathology — stopout near
    # certain at typical XAU spreads of $0.20-0.50).
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
        sl_floor = 4.0
        rr_floor = 1.5
        target_rr_cap = 3.0  # max TP distance as multiple of SL distance
    else:
        sl_floor = sl_min_distance
        rr_floor = 2.0
        target_rr_cap = None  # no cap — honor structural swing/FVG targets

    # ========== 🤖 ENSEMBLE ML INTEGRATION ==========
    ensemble_result = None
    ml_signal = None

    # Pobierz live data z Twelve Data jeśli nie podany df.
    # Match the ML-analysis TF to the signal TF. Old behavior hardcoded 15m
    # regardless of whether scanner fired on 5m / 15m / 30m / 1h / 4h — ensemble
    # predictions on 15m data for a 5m-triggered trade were timing-mismatched.
    # 5m/15m/30m use their own candle window; 1h/4h still fall back to 15m
    # because that's the smallest window ML models were trained on (using 1h+
    # candles here needs 200 bars → 2+ weeks, overkill for ML signal).
    if df is None:
        try:
            from src.data.data_sources import get_provider
            provider = get_provider()
            ml_tf = tf_signal if tf_signal in ('5m', '15m', '30m') else '15m'
            logger.debug(f"📡 Fetching live {ml_tf} candles from Twelve Data for ML analysis")
            df = provider.get_candles('XAU/USD', ml_tf, 200)
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
            # 2026-05-02 audit lowered scalp threshold 0.65 → 0.50. The 0.65
            # gate was set when LSTM_BULLISH_ONLY masked LSTM bearish votes —
            # post-Phase-8 retrain (2026-04-30) all 4 ML voters bidirectional,
            # so a 0.50 conviction from the ensemble is now substantively
            # different from "model uncertain". Earlier high gate let the
            # 5/5 LONG-LOSS streak through despite ensemble weak-LONG votes.
            #
            # Toxic-imminent override: if scanner tagged the SMC pattern as
            # near-toxic (n>=15 WR<35%), drop the conflict threshold to ZERO
            # — any ML disagreement with conviction blocks. This lets the
            # system self-defend BEFORE the full toxic n>=20 threshold engages.
            toxic_imminent = analysis_data.get('_toxic_imminent', False)
            if toxic_imminent:
                conflict_threshold = 0.30
            else:
                conflict_threshold = 0.50 if is_scalp else 0.55
            if ensemble_result.get('confidence', 0) > conflict_threshold:
                _bump_metric("trades_rejected")
                tox_note = f" (TOXIC-IMM gate)" if toxic_imminent else ""
                return {
                    "direction": "CZEKAJ",
                    "reason": f"ML ({ml_signal}, {ensemble_result.get('confidence', 0):.0%}) konflikt z SMC ({direction}){tox_note} — czekamy",
                    "ensemble_data": ensemble_result
                }
    # ML support REQUIRED when SMC pattern is toxic-imminent (out of conflict
    # branch — fires whether ML agrees, disagrees, or is CZEKAJ as long as
    # the pattern is at-risk). Logic: pattern WR<35% with n>=15 means the
    # SMC signal alone is no longer reliable; demand ML actively support.
    toxic_imminent_outer = analysis_data.get('_toxic_imminent', False)
    if toxic_imminent_outer and ensemble_result:
        if ml_signal == "CZEKAJ":
            _bump_metric("trades_rejected")
            return {
                "direction": "CZEKAJ",
                "reason": (
                    f"toxic-imminent {analysis_data.get('_toxic_pattern_key','?')} "
                    f"WR={analysis_data.get('_toxic_wr',0):.0%} "
                    f"(n={analysis_data.get('_toxic_n','?')}) requires active ML support, "
                    f"got CZEKAJ"
                ),
                "ensemble_data": ensemble_result
            }
        # ML active but disagrees → handled by conflict block above with the
        # 0.30 threshold. ML active and agrees → proceed.

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

        # Dynamic R:R per grade — TARGET-PROFIT calls (where TP sits relative
        # to SL). 2026-05-05: source of truth is `score_setup_quality` (sets
        # target_rr per grade); finance.py respects it instead of overriding.
        # The previous `max(tp_to_sl_ratio, X)` floor silently bumped RR back
        # to baseline whenever dynamic_params.tp_to_sl_ratio was higher than
        # smc_engine's choice — undid the 2026-05-05 A-demote (commit fa98fb0)
        # and any future tighter RR call. Now we accept smc_engine's per-grade
        # target_rr verbatim. dynamic_params.tp_to_sl_ratio remains the
        # baseline only when no setup_quality is available (fallback below).
        new_target_rr = setup_quality.get('target_rr')
        if new_target_rr and new_target_rr > 0:
            tp_to_sl_ratio = new_target_rr

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
    # Scalp mode (5m): sl_floor = 4.0, rr_floor = 1.5, TP capped at 3R.
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

    # Flat-risk override (Lot Sizing Option A — design doc 2026-04-27).
    # OFF by default (USE_FLAT_RISK unset/0). When enabled, replaces all of
    # Kelly + daily/session/vol multipliers + loss-streak compounding with
    # a single explicit percentage of equity. Decision gate to flip is
    # 2026-05-04 (24-72h live obs of Phase B + B7 + MAX_LOT_CAP=0.01 baseline).
    # See docs/strategy/2026-04-27_lot_sizing_rebuild_design.md.
    if os.environ.get("USE_FLAT_RISK") == "1":
        _flat_pct = float(os.environ.get("FLAT_RISK_PCT", "0.5"))
        _legacy_pct = risk_percent_adj
        risk_percent_adj = _flat_pct
        logger.info(
            f"[FLAT_RISK] override active: {_flat_pct:.2f}% "
            f"(legacy path would have used {_legacy_pct:.2f}%)"
        )

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

    # B6 (2026-04-26): direction-based risk multiplier. Set
    # QUANT_RISK_LONG_MULT or QUANT_RISK_SHORT_MULT to a float in (0, 1.5]
    # to scale lot size for that direction. Non-eliminating defense for
    # LONG asymmetry (every LONG factor has -EV per attribution data) —
    # use 0.5 to halve LONG risk while collecting more samples. Reversible.
    try:
        if direction == "LONG":
            _dir_mult = float(os.environ.get("QUANT_RISK_LONG_MULT", "1.0"))
        elif direction == "SHORT":
            _dir_mult = float(os.environ.get("QUANT_RISK_SHORT_MULT", "1.0"))
        else:
            _dir_mult = 1.0
        if 0 < _dir_mult < 1.5 and abs(_dir_mult - 1.0) > 0.001:
            original_lot = lot_size
            lot_size = round(lot_size * _dir_mult, 2)
            if lot_size < 0.01:
                lot_size = 0.01
            logger.info(f"[B6] {direction} risk × {_dir_mult}: {original_lot} → {lot_size} lot")
    except (ValueError, TypeError):
        pass

    # MAX_LOT_CAP (2026-04-26): hard ceiling on lot size, enforced AFTER all
    # other lot-sizing logic. Set in .env to cap risk while the lot-sizing
    # rebuild lands. Backtest 2026-04-26 found lot was inverse-correlated
    # with outcome (winners avg 0.026, losers 0.084) — A+ grade 1.5× risk
    # bump bet bigger on losing setups. Equal-lot 0.01 backtest produced
    # PF 1.80 / +7.18% return / -4.23% DD; same strategy with var lot ran
    # PF 1.66 / -20.7% return / -26% DD. Cap is safety floor until rebuild.
    try:
        _max_lot = float(os.environ.get("MAX_LOT_CAP", "0.5"))
    except (ValueError, TypeError):
        _max_lot = 0.5
    if lot_size > _max_lot:
        logger.info(f"[MAX_LOT_CAP] lot {lot_size} → {_max_lot}")
        lot_size = _max_lot

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
            # 2026-05-02: surface ml_majority_disagrees + model_agreement
            # so scanner can gate on them without recomputing.
            'ml_majority_disagrees': ensemble_result.get('ml_majority_disagrees', False),
            'model_agreement': ensemble_result.get('model_agreement', {}),
            'predictions': {
                k: {
                    'direction': v.get('direction'),
                    'confidence': round(v.get('confidence', 0), 2),
                    'status': v.get('status', 'ok')
                } for k, v in ensemble_result.get('predictions', {}).items()
            }
        }

    return result
