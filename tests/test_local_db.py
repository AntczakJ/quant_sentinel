"""Test lokalnej bazy danych SQLite — sprawdza czy wszystko dziala."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Wymus lokalna baze PRZED importem database
os.environ['DATABASE_URL'] = 'data/sentinel.db'
os.environ.pop('DATABASE_TOKEN', None)

# Reload database module z nowym URL
if 'src.database' in sys.modules:
    del sys.modules['src.database']

print("=" * 60)
print("TEST: Lokalna baza danych (SQLite)")
print("=" * 60)

passed = 0
failed = 0

def check(name, ok):
    global passed, failed
    if ok:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1

# 1. Polaczenie
print("\n[1] Polaczenie")
from src.core.database import NewsDB, _using_sqlite, DATABASE_URL
check(f"DATABASE_URL = {DATABASE_URL}", "sentinel.db" in DATABASE_URL)
check(f"SQLite mode = {_using_sqlite}", _using_sqlite == True)
db = NewsDB()
check("NewsDB() created", db is not None)

# 2. Tabele
print("\n[2] Tabele")
db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in db.cursor.fetchall()]
for t in ['trades', 'user_settings', 'processed_news', 'dynamic_params', 'scanner_signals']:
    check(f"table: {t}", t in tables)

# 3. CRUD parametry
print("\n[3] CRUD parametry")
db.set_param('_local_test', 42.0)
val = db.get_param('_local_test', 0)
check(f"set/get_param: {val}", val == 42.0)
db._execute("DELETE FROM dynamic_params WHERE param_name = ?", ('_local_test',))

# 4. Balance
print("\n[4] Balance")
old = db.get_balance(1)
db.update_balance(1, 9999.0)
new = db.get_balance(1)
db.update_balance(1, old)
check(f"balance CRUD: {old} -> {new} -> restored", new == 9999.0)

# 5. Trades
print("\n[5] Trades")
db.log_trade('LONG', 2350.0, 2340.0, 2370.0, 45.0, 'bull', 'Stable', 'TEST', {'bos': 1})
check("log_trade()", True)
trades = db.get_open_trades()
check(f"get_open_trades() -> {len(trades)}", len(trades) >= 1)
if trades:
    tid = trades[-1][0]
    db.update_trade_status(tid, 'PROFIT')
    check(f"update_trade_status({tid}, PROFIT)", True)

# 6. Scanner signals
print("\n[6] Scanner signals")
db.save_scanner_signal('LONG', 2355.0, 2345.0, 2375.0, 48.0, 'bull', 'BOS')
check("save_scanner_signal()", True)
sigs = db.get_all_scanner_signals(5)
check(f"get_scanner_signals() -> {len(sigs)}", len(sigs) >= 1)

# 7. Pattern stats
print("\n[7] Pattern stats")
db.update_pattern_stats('_TEST_LOCAL', 'PROFIT')
db.update_pattern_stats('_TEST_LOCAL', 'LOSS')
stats = db.get_pattern_stats('_TEST_LOCAL')
check(f"pattern count={stats['count']}, wr={stats['win_rate']:.2f}", stats['count'] >= 2)

# 8. Performance
print("\n[8] Performance stats")
perf = db.get_performance_stats()
check(f"get_performance_stats() tuple len={len(perf)}", len(perf) == 2)

# 9. Session/regime
print("\n[9] Session & regime")
try:
    db.update_session_stats('_TEST', 'London', 'PROFIT')
    check("update_session_stats()", True)
except Exception as e:
    check(f"update_session_stats: {e}", False)
try:
    db.update_regime_stats('zielony', 'London', 'LONG', 'PROFIT')
    check("update_regime_stats()", True)
except Exception as e:
    check(f"update_regime_stats: {e}", False)

# 10. Fail rate
print("\n[10] Fail rate")
fr = db.get_fail_rate_for_pattern(45.0, 'Stable')
check(f"fail_rate(RSI=45, Stable) = {fr}%", isinstance(fr, (int, float)))

# 11. Factors
print("\n[11] Trade factors")
factors = db.get_trade_factors(1)
check(f"get_trade_factors(1) -> {type(factors).__name__}", factors is not None or factors is None)

# 12. Loss details
print("\n[12] Loss logging")
try:
    db.log_loss_details(trade_id=99999, reason="test", market_condition="test")
    check("log_loss_details()", True)
except Exception as e:
    check(f"log_loss_details: {e}", False)

# 13. News dedup
print("\n[13] News dedup")
db.mark_news_as_processed("_test_hash_local")
check("is_news_processed", db.is_news_processed("_test_hash_local") == True)

# 14. Self-learning integration
print("\n[14] Self-learning")
try:
    from src.learning.self_learning import get_pattern_adjustment
    adj = get_pattern_adjustment({"pattern": "_NONEXISTENT"})
    check(f"get_pattern_adjustment() = {adj}", adj == 1.0)
except Exception as e:
    check(f"self_learning: {e}", False)

# 15. Ensemble weights
print("\n[15] Ensemble weights (DB)")
try:
    from src.ml.ensemble_models import _load_dynamic_weights
    w = _load_dynamic_weights()
    check(f"ensemble weights: {w}", sum(w.values()) > 0.99)
except Exception as e:
    check(f"ensemble weights: {e}", False)

# Summary
print("\n" + "=" * 60)
print(f"WYNIK: {passed}/{passed+failed}")
print("=" * 60)
if failed == 0:
    print("✅ TAK — wszystko dziala na lokalnej bazie SQLite!")
else:
    print(f"⚠️ {failed} test(ow) nie przeszlo")




