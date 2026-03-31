# finance.py
"""
finance.py — obliczenia finansowe i zarządzanie ryzykiem.
"""

import requests


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


def calculate_position(analysis_data: dict, balance: float, user_currency: str, td_api_key: str) -> dict:
    """
    Oblicza pozycję z filtrami ekonomicznymi:
    - minimalny zysk 10 USD
    - minimalny dystans TP (ATR lub 2$)
    """
    # Dane z silnika SMC
    from src.database import NewsDB
    db = NewsDB()

    risk_percent = db.get_param("risk_percent", 1.0)
    min_profit_usd = db.get_param("min_profit_usd", 10.0)
    min_tp_distance_mult = db.get_param("min_tp_distance_mult", 1.0)
    target_rr = db.get_param("target_rr", 2.5)
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

    # --- 1. Ustal kierunek ---
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

    # Filtrowanie makro
    if macro_regime == "czerwony" and direction == "LONG":
        return {"direction": "CZEKAJ", "reason": "Makro czerwony – przeciwwskazanie do LONG"}
    if macro_regime == "zielony" and direction == "SHORT":
        return {"direction": "CZEKAJ", "reason": "Makro zielony – przeciwwskazanie do SHORT"}

    # --- 2. SL i TP ---
    if direction == "LONG":
        if grab and grab_dir == "bullish":
            sl = round(swing_low - 1.0, 2)
        else:
            sl = round(entry - 2.0, 2)

        if fvg_type == "bullish" and fvg_upper and fvg_upper > entry:
            tp = round(fvg_upper, 2)
        else:
            if swing_high and swing_high > entry:
                tp = round(swing_high + 2.0, 2)
            else:
                tp = round(entry + max(atr, 2.0), 2)

        if tp <= entry:
            tp = round(entry + max(atr, 2.0), 2)

    else:  # SHORT
        if grab and grab_dir == "bearish":
            sl = round(swing_high + 1.0, 2)
        else:
            sl = round(entry + 2.0, 2)

        if fvg_type == "bearish" and fvg_lower and fvg_lower < entry:
            tp = round(fvg_lower, 2)
        else:
            if swing_low and swing_low < entry:
                tp = round(swing_low - 2.0, 2)
            else:
                tp = round(entry - max(atr, 2.0), 2)

        if tp >= entry:
            tp = round(entry - max(atr, 2.0), 2)

    # --- 3. Waluta i kapitał ---
    balance_in_usd = balance
    if user_currency != "USD":
        try:
            rate_url = f"https://api.twelvedata.com/price?symbol=USD/{user_currency}&apikey={td_api_key}"
            r = requests.get(rate_url, timeout=5).json()
            rate = float(r.get('price', 4.0))
            balance_in_usd = balance / rate
        except:
            balance_in_usd = balance / 4.0

    # --- 4. Wielkość lota (1% ryzyka) ---
    risk_usd = balance_in_usd * (risk_percent / 100)



    dist = abs(entry - sl)
    if dist <= 0:
        dist = 2.0
    lot_size = round(risk_usd / (dist * 100), 2)
    if lot_size < 0.01:
        lot_size = 0.01  # minimum brokera

    potential_profit_usd = abs(entry - tp) * lot_size * 100

    # --- 6. Filtry ekonomiczne (po obliczeniu lot_size) ---
    if potential_profit_usd < min_profit_usd:
        return {"direction": "CZEKAJ",
                "reason": f"Zbyt mały zysk ({potential_profit_usd:.2f}$) – minimalny {min_profit_usd}$."}

    min_tp_distance = max(atr * min_tp_distance_mult, 2.0)
    if abs(entry - tp) < min_tp_distance:
        return {"direction": "CZEKAJ", "reason": f"Zbyt mały dystans TP – minimalny {min_tp_distance}$."}

    # --- 7. Zwrot pozycji ---
    return {
        'lot': lot_size,
        'sl': sl,
        'tp': tp,
        'entry': entry,
        'direction': direction,
        'logic': logic
    }