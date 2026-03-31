"""
tracker.py — ZDEPRECJONOWANY moduł śledzenia transakcji (plik JSON).

⚠️ TEN MODUŁ NIE JEST JUŻ UŻYWANY przez głównego bota.

Wcześniej był wywoływany z scanner.py równolegle z bazą SQLite (database.py),
co powodowało podwójne rozliczanie pozycji i niespójne statystyki.

Jedynym aktywnym systemem śledzenia transakcji jest teraz:
    src/database.py → tabela 'trades' w data/sentinel.db (SQLite)

Plik pozostawiony w repozytorium wyłącznie jako referencja historyczna.
Nie importuj tego modułu w nowym kodzie.

Jeśli chcesz wyeksportować stary plik trades.json do bazy SQLite,
możesz użyć poniższego skryptu migracyjnego (uruchom raz ręcznie):

    import json, sqlite3
    with open('trades.json') as f:
        trades = json.load(f)
    conn = sqlite3.connect('data/sentinel.db')
    for t in trades:
        direction = t.get('direction', '').replace(' 🔴', '').replace(' 🟢', '').strip()
        status = 'LOSS' if 'LOSS' in t.get('status', '') else \
                 'PROFIT' if 'PROFIT' in t.get('status', '') else 'OPEN'
        conn.execute(
            "INSERT INTO trades (timestamp, direction, entry, sl, tp, status) VALUES (?,?,?,?,?,?)",
            (t['timestamp'], direction, t['entry'], t['sl'], t['tp'], status)
        )
    conn.commit()
    conn.close()
    print("Migracja zakończona.")
"""

import json
import os
from datetime import datetime

TRADES_FILE = "trades.json"


def save_trade(trade_data: dict):
    """
    [ZDEPRECJONOWANE] Zapisuje trade do pliku JSON.
    Używaj db.log_trade() z src/database.py zamiast tej funkcji.
    """
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            trades = json.load(f)

    trade_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    trade_data["status"] = "OPEN"
    trades.append(trade_data)

    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=4)


def update_trades(current_price: float) -> list:
    """
    [ZDEPRECJONOWANE] Sprawdza i rozlicza pozycje w pliku JSON.
    Używaj resolve_trades_task() z src/scanner.py zamiast tej funkcji.
    """
    if not os.path.exists(TRADES_FILE):
        return []

    with open(TRADES_FILE, "r") as f:
        trades = json.load(f)

    results = []
    for t in trades:
        if t["status"] == "OPEN":
            if "LONG" in t["direction"]:
                if current_price >= t["tp"]:
                    t["status"] = "PROFIT ✅"
                    results.append(t)
                elif current_price <= t["sl"]:
                    t["status"] = "LOSS ❌"
                    results.append(t)
            else:
                if current_price <= t["tp"]:
                    t["status"] = "PROFIT ✅"
                    results.append(t)
                elif current_price >= t["sl"]:
                    t["status"] = "LOSS ❌"
                    results.append(t)

    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=4)

    return results


def get_stats() -> str:
    """
    [ZDEPRECJONOWANE] Oblicza Win Rate z pliku JSON.
    Używaj db.get_performance_stats() z src/database.py zamiast tej funkcji.
    """
    if not os.path.exists(TRADES_FILE):
        return "Brak danych."

    with open(TRADES_FILE, "r") as f:
        trades = json.load(f)

    closed = [t for t in trades if t["status"] in ["PROFIT ✅", "LOSS ❌"]]
    if not closed:
        return "Brak rozliczonych pozycji."

    wins = len([t for t in closed if "PROFIT" in t["status"]])
    win_rate = (wins / len(closed)) * 100

    return (
        f"📊 *STATYSTYKI SYSTEMU:*\n"
        f"✅ Zyski: `{wins}`\n"
        f"❌ Straty: `{len(closed) - wins}`\n"
        f"📈 Win Rate: *{win_rate:.1f}%*"
    )
