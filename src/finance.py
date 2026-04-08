# finance.py
"""
finance.py — obliczenia finansowe i zarządzanie ryzykiem.

Zmiany:
- Stały minimalny dystans TP = 5$.
- Dodano dynamiczny filtr: min_tp_distance = max(atr * min_tp_distance_mult, 5.0).
- Parametr min_tp_distance_mult jest przechowywany w dynamic_params i może być optymalizowany.
- Kurs walutowy pobierany przez DataProvider (nie bezpośrednie requesty).
"""

from src.logger import logger


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


def calculate_position(analysis_data: dict, balance: float, user_currency: str, td_api_key: str, df=None) -> dict:
    """
    SMC MASTER VERSION: Oblicza pozycję w oparciu o Liquidity Grab, MSS, FVG, DBR/RBD, makro i ALL ML MODELS.

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

    # --- FILTR SESJI: skip Asian session (zbyt niska zmienność → noise stops) ---
    if session == 'asian':
        return {"direction": "CZEKAJ", "reason": "Sesja azjatycka — zbyt niska zmienność na XAU/USD"}

    # Pobranie dynamicznych parametrów (zamiast hardcoded)
    from src.database import NewsDB
    db = NewsDB()
    risk_percent = db.get_param("risk_percent", 1.0)
    min_tp_distance_mult = db.get_param("min_tp_distance_mult", 1.0)
    sl_atr_mult = db.get_param("sl_atr_multiplier", 1.5)
    sl_min_distance = db.get_param("sl_min_distance", 4.0)
    tp_to_sl_ratio = db.get_param("tp_to_sl_ratio", 2.5)

    # ========== 🤖 ENSEMBLE ML INTEGRATION ==========
    ensemble_result = None
    ml_signal = None

    # Pobierz live data z Twelve Data jeśli nie podany df
    if df is None:
        try:
            from src.data_sources import get_provider
            provider = get_provider()
            logger.debug("📡 Fetching live candles from Twelve Data for ML analysis")
            df = provider.get_candles('XAU/USD', '15m', 200)
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch live data: {e}")
            df = None

    if df is not None and not df.empty:
        try:
            from src.ensemble_models import get_ensemble_prediction
            initial_balance = balance  # Założenie, że balance to obecny stan
            ensemble_result = get_ensemble_prediction(
                df=df,
                smc_trend=trend,
                current_price=price,
                balance=balance,
                initial_balance=initial_balance,
                position=0,  # TODO: pobrać z bazy danych
                use_twelve_data=False  # Już mamy df, nie pobieraj ponownie
            )
            ml_signal = ensemble_result['ensemble_signal']
            logger.info(f"🤖 ML Ensemble Signal: {ml_signal} (confidence: {ensemble_result['confidence']:.1%})")
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
            entry = ob_price if ob_price < price else price
            logic = "Liquidity Grab + MSS (Bearish)"
    elif dbr_rbd_type == "DBR":
        direction = "LONG"
        entry = base_high if base_high else price
        logic = "DBR (Drop-Base-Rally)"
    elif dbr_rbd_type == "RBD":
        direction = "SHORT"
        entry = base_low if base_low else price
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
            logic += f" [ML: {ensemble_result['confidence']:.0%}✅]"
        else:
            # SMC i ML się NIE zgadzają
            logger.warning(f"⚠️ SMC ({direction}) vs ML ({ml_signal}) KONFLIKT (confidence: {ensemble_result['confidence']:.0%})")
            logic += f" [ML: {ensemble_result['confidence']:.0%}⚠️]"

            # BLOKADA: Jeśli ML ma wysoką pewność i mówi inaczej niż SMC — nie otwieraj trade'a
            if ensemble_result['confidence'] > 0.55:
                return {
                    "direction": "CZEKAJ",
                    "reason": f"ML ({ml_signal}, {ensemble_result['confidence']:.0%}) konflikt z SMC ({direction}) — czekamy",
                    "ensemble_data": ensemble_result
                }

    # Filtrowanie makro
    if macro_regime == "czerwony" and direction == "LONG":
        return {"direction": "CZEKAJ", "reason": "Makro czerwony – przeciwwskazanie do LONG"}
    if macro_regime == "zielony" and direction == "SHORT":
        return {"direction": "CZEKAJ", "reason": "Makro zielony – przeciwwskazanie do SHORT"}

    # ========== FILTR PEWNOŚCI ENSEMBLE ==========
    if ensemble_result and ensemble_result['confidence'] < 0.4 and ml_signal == "CZEKAJ":
        return {
            "direction": "CZEKAJ",
            "reason": f"Niska pewność ensemble ({ensemble_result['confidence']:.1%}) - czekamy na wyraźniejszy sygnał",
            "ensemble_data": ensemble_result
        }

    # --- 2. SL i TP ---
    # SL oparty na ATR zamiast stałego 2.0$ — zapobiega wyrzucaniu przez szum rynkowy
    # Parametry z bazy: sl_atr_mult (def 1.5), sl_min_distance (def 4.0)
    sl_distance = max(atr * sl_atr_mult, sl_min_distance) * sl_multiplier

    if direction == "LONG":
        if grab and grab_dir == "bullish" and swing_low:
            # Grab setup: SL pod swing low z buforem
            sl = round(swing_low - max(atr * 0.3, 1.0), 2)
            # Upewnij się że SL nie jest za ciasny nawet przy grab
            if entry - sl < sl_distance * 0.7:
                sl = round(entry - sl_distance, 2)
        else:
            sl = round(entry - sl_distance, 2)

        # TP: cel bazowany na strukturze rynkowej
        tp_distance = sl_distance * tp_to_sl_ratio
        if fvg_type == "bullish" and fvg_upper and fvg_upper > entry + sl_distance:
            tp = round(fvg_upper, 2)
        elif swing_high and swing_high > entry + sl_distance:
            tp = round(swing_high, 2)
        else:
            tp = round(entry + tp_distance, 2)

        if tp <= entry + sl_distance:
            tp = round(entry + tp_distance, 2)

    else:  # SHORT
        if grab and grab_dir == "bearish" and swing_high:
            sl = round(swing_high + max(atr * 0.3, 1.0), 2)
            if sl - entry < sl_distance * 0.7:
                sl = round(entry + sl_distance, 2)
        else:
            sl = round(entry + sl_distance, 2)

        tp_distance = sl_distance * 2.5
        if fvg_type == "bearish" and fvg_lower and fvg_lower < entry - sl_distance:
            tp = round(fvg_lower, 2)
        elif swing_low and swing_low < entry - sl_distance:
            tp = round(swing_low, 2)
        else:
            tp = round(entry - tp_distance, 2)

        if tp >= entry - sl_distance:
            tp = round(entry - tp_distance, 2)

    # --- 3. Waluta i kapitał ---
    balance_in_usd = balance
    if user_currency != "USD":
        try:
            from src.data_sources import get_provider
            provider = get_provider()
            rate = provider.get_exchange_rate("USD", user_currency)
            if rate is None:
                rate = 4.0
            balance_in_usd = balance / rate
        except:
            balance_in_usd = balance / 4.0

    # --- 4. Wielkość lota (ryzyko %) ---
    risk_usd = balance_in_usd * (risk_percent / 100)
    dist = abs(entry - sl)
    if dist <= 0:
        dist = 2.0
    lot_size = round(risk_usd / (dist * 100), 2)
    if lot_size < 0.01:
        lot_size = 0.01

    # --- 5. FILTR: minimalny dystans TP ---
    MIN_TP_DISTANCE = 5.0
    dynamic_min_distance = atr * min_tp_distance_mult
    min_distance = max(dynamic_min_distance, MIN_TP_DISTANCE)

    if abs(entry - tp) < min_distance:
        return {"direction": "CZEKAJ",
                "reason": f"Zbyt mały dystans TP ({abs(entry - tp):.2f}$) – minimalny {min_distance:.2f}$."}

    result = {
        'lot': lot_size,
        'sl': sl,
        'tp': tp,
        'entry': entry,
        'direction': direction,
        'logic': logic
    }

    # Dodaj ML ensemble data jeśli dostępna
    if ensemble_result:
        result['ensemble_data'] = {
            'signal': ensemble_result['ensemble_signal'],
            'final_score': round(ensemble_result['final_score'], 3),
            'confidence': round(ensemble_result['confidence'], 2),
            'models_available': ensemble_result['models_available'],
            'predictions': {
                k: {
                    'direction': v.get('direction'),
                    'confidence': round(v.get('confidence', 0), 2),
                    'status': v.get('status', 'ok')
                } for k, v in ensemble_result['predictions'].items()
            }
        }

    return result
