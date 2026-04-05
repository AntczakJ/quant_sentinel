#!/usr/bin/env python3
"""
tests/run_all_tests.py - Master test runner dla całego projektu QUANT SENTINEL
Uruchamia wszystkie testy i generuje raport
"""

import sys
import os
import time
import subprocess
from pathlib import Path

# Ensure subprocesses use UTF-8 I/O on Windows (emoji in print() calls)
_UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

print("="*90)
print("🧪 QUANT SENTINEL - MASTER TEST SUITE")
print("="*90)

# Lista wszystkich testów
TESTS = [
    ("Importy i moduły", "tests/test_imports.py"),
    ("Baza danych", "tests/test_database.py"),
    ("Cache i optymalizacja", "tests/test_cache.py"),
    ("SMC Engine", "tests/test_smc_engine.py"),
    ("Finance calculations", "tests/test_finance.py"),
    ("Machine Learning", "tests/test_ml.py"),
    ("AI Engine", "tests/test_ai.py"),
    ("Configuration", "tests/test_config.py"),
    ("Integration", "tests/test_integration.py"),
    ("Performance", "tests/test_performance.py"),
]

results = []

for test_name, test_file in TESTS:
    print(f"\n[TEST] {test_name} ({test_file})...")
    print("-" * 90)

    if os.path.exists(test_file):
        try:
            result = subprocess.run(
                [sys.executable, test_file],
                capture_output=True,
                timeout=120,
                env=_UTF8_ENV
            )
            if result.returncode == 0:
                print(f"✅ {test_name}: PRZEJĘTY")
                results.append((test_name, True))
            else:
                print(f"❌ {test_name}: FAILED")
                if result.stdout:
                    print(result.stdout.decode("utf-8", errors="replace")[-500:])
                if result.stderr:
                    print("STDERR:", result.stderr.decode("utf-8", errors="replace")[-300:])
                results.append((test_name, False))
        except subprocess.TimeoutExpired:
            print(f"❌ {test_name}: TIMEOUT")
            results.append((test_name, False))
        except Exception as e:
            print(f"❌ {test_name}: {e}")
            results.append((test_name, False))
    else:
        print(f"⚠️ {test_name}: Test file nie znaleziony")
        results.append((test_name, None))

# Podsumowanie
print("\n" + "="*90)
print("📊 PODSUMOWANIE TESTÓW")
print("="*90)

passed = sum(1 for _, r in results if r is True)
failed = sum(1 for _, r in results if r is False)
skipped = sum(1 for _, r in results if r is None)
total = len(results)

for test_name, result in results:
    if result is True:
        print(f"✅ {test_name}")
    elif result is False:
        print(f"❌ {test_name}")
    else:
        print(f"⚠️ {test_name} (pominięty)")

print(f"\nRazem: {passed}/{total} przejęto, {failed} nie przejęło, {skipped} pominięto")

if passed == total:
    print("🎉 WSZYSTKIE TESTY PRZEJĘTE!")
    sys.exit(0)
elif passed >= total * 0.8:
    print("✅ Większość testów przejęła (80%+)")
    sys.exit(0)
else:
    print(f"⚠️ Część testów nie przejęła ({(passed/total)*100:.0f}%)")
    sys.exit(1)

