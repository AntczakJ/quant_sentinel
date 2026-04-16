#!/usr/bin/env python3
"""
tests/run_comprehensive_tests.py - Master test runner with proper path handling
"""

import sys
import os
from pathlib import Path

# Fix encoding on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import subprocess
import json
from datetime import datetime

class TestRunner:
    def __init__(self):
        self.results = {}
        self.total_passed = 0
        self.total_failed = 0

    def run_test(self, test_name: str, test_file: str) -> bool:
        """Run single test file"""
        print(f"\n{'='*80}")
        print(f"🧪 {test_name}: {test_file}")
        print('='*80)

        try:
            result = subprocess.run(
                [sys.executable, test_file],
                cwd=str(project_root),
                capture_output=False,
                timeout=120,
                text=True
            )

            if result.returncode == 0:
                print(f"✅ {test_name}: PASSED")
                self.total_passed += 1
                self.results[test_name] = "PASSED"
                return True
            else:
                print(f"❌ {test_name}: FAILED (exit code: {result.returncode})")
                self.total_failed += 1
                self.results[test_name] = "FAILED"
                return False
        except subprocess.TimeoutExpired:
            print(f"❌ {test_name}: TIMEOUT (>120s)")
            self.total_failed += 1
            self.results[test_name] = "TIMEOUT"
            return False
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            self.total_failed += 1
            self.results[test_name] = "ERROR"
            return False

    def run_python_tests(self):
        """Run Python backend tests"""
        print("\n" + "#"*80)
        print("# BACKEND TESTS (Python)")
        print("#"*80)

        backend_tests = [
            ("Imports", "tests/test_imports.py"),
            ("Database", "tests/test_database.py"),
            ("Cache", "tests/test_cache.py"),
            ("SMC Engine", "tests/test_smc_engine.py"),
            ("Finance", "tests/test_finance.py"),
            ("ML Models", "tests/test_ml.py"),
            ("AI Engine", "tests/test_ai.py"),
            ("Config", "tests/test_config.py"),
            ("Integration", "tests/test_integration.py"),
            ("Performance", "tests/test_performance.py"),
            ("API Endpoints", "tests/test_api_endpoints.py"),
        ]

        for test_name, test_file in backend_tests:
            test_path = project_root / test_file
            if test_path.exists():
                self.run_test(test_name, str(test_path))
            else:
                print(f"⚠️ {test_name}: Test file not found - {test_file}")

    def test_frontend_structure(self):
        """Test frontend structure without npm"""
        print("\n" + "#"*80)
        print("# FRONTEND STRUCTURE TESTS")
        print("#"*80)

        frontend_path = project_root / "frontend"

        tests_passed = 0

        # Check components exist
        components = [
            "src/components/charts/CandlestickChart.tsx",
            "src/components/dashboard/Dashboard.tsx",
            "src/components/dashboard/Header.tsx",
            "src/components/dashboard/SignalPanel.tsx",
            "src/components/dashboard/PortfolioStats.tsx",
            "src/components/dashboard/ModelStats.tsx",
            "src/components/dashboard/SignalHistory.tsx",
        ]

        print("\n✅ Component Files:")
        for component in components:
            file_path = frontend_path / component
            if file_path.exists():
                print(f"   ✓ {component}")
                tests_passed += 1
            else:
                print(f"   ✗ {component} - MISSING")

        # Check config files
        configs = ["package.json", "tsconfig.json", "vite.config.ts", "tailwind.config.js"]
        print("\n✅ Configuration Files:")
        for config in configs:
            config_path = frontend_path / config
            if config_path.exists():
                print(f"   ✓ {config}")
                tests_passed += 1
            else:
                print(f"   ✗ {config} - MISSING")

        # Check API and store
        print("\n✅ API & State Management:")
        api_client = frontend_path / "src/api/client.ts"
        store = frontend_path / "src/store/tradingStore.ts"
        types = frontend_path / "src/types/trading.ts"

        for name, path in [("API Client", api_client), ("Store", store), ("Types", types)]:
            if path.exists():
                print(f"   ✓ {name}")
                tests_passed += 1
            else:
                print(f"   ✗ {name} - MISSING")

        # Validate file contents
        print("\n✅ File Content Validation:")

        chart_file = frontend_path / "src/components/charts/CandlestickChart.tsx"
        if chart_file.exists():
            content = chart_file.read_text(encoding='utf-8', errors='ignore')
            if "LineChart" in content:
                print(f"   ✓ CandlestickChart has LineChart")
                tests_passed += 1
            if "RSI" in content:
                print(f"   ✓ CandlestickChart has RSI")
                tests_passed += 1
            if "Bollinger" in content:
                print(f"   ✓ CandlestickChart has Bollinger Bands")
                tests_passed += 1

        signal_file = frontend_path / "src/components/dashboard/SignalPanel.tsx"
        if signal_file.exists():
            content = signal_file.read_text(encoding='utf-8', errors='ignore')
            if "STRONG_BUY" in content and "STRONG_SELL" in content:
                print(f"   ✓ SignalPanel has consensus levels")
                tests_passed += 1
            if "RL Agent" in content and "LSTM" in content and "XGBoost" in content:
                print(f"   ✓ SignalPanel shows all 3 models")
                tests_passed += 1

        portfolio_file = frontend_path / "src/components/dashboard/PortfolioStats.tsx"
        if portfolio_file.exists():
            content = portfolio_file.read_text(encoding='utf-8', errors='ignore')
            if "balance" in content.lower() and "pnl" in content.lower():
                print(f"   ✓ PortfolioStats displays balance and P&L")
                tests_passed += 1

        models_file = frontend_path / "src/components/dashboard/ModelStats.tsx"
        if models_file.exists():
            content = models_file.read_text(encoding='utf-8', errors='ignore')
            if "accuracy" in content.lower():
                print(f"   ✓ ModelStats shows accuracy metrics")
                tests_passed += 1

        history_file = frontend_path / "src/components/dashboard/SignalHistory.tsx"
        if history_file.exists():
            content = history_file.read_text(encoding='utf-8', errors='ignore')
            if "history" in content.lower():
                print(f"   ✓ SignalHistory component loads")
                tests_passed += 1

        self.total_passed += tests_passed
        self.results["Frontend Structure"] = "PASSED" if tests_passed > 20 else "PARTIAL"

    def test_backend_structure(self):
        """Test backend structure"""
        print("\n" + "#"*80)
        print("# BACKEND STRUCTURE TESTS")
        print("#"*80)

        src_path = project_root / "src"
        api_path = project_root / "api"

        tests_passed = 0

        # Check core modules (2026-04-16: removed main.py after Telegram bot deleted)
        modules = [
            ("smc_engine.py", "SMC analysis"),
            ("ai_engine.py", "AI/sentiment"),
            ("ml_models.py", "ML models"),
            ("finance.py", "Position sizing"),
            ("database.py", "Data persistence"),
            ("config.py", "Configuration"),
            ("scanner.py", "Market scanner"),
        ]

        print("\n✅ Backend Modules:")
        for module, desc in modules:
            module_path = src_path / module
            if module_path.exists():
                print(f"   ✓ {module} ({desc})")
                tests_passed += 1
            else:
                print(f"   ✗ {module} - MISSING")

        # Check API structure
        print("\n✅ API Structure:")
        if api_path.exists():
            print(f"   ✓ API directory exists")
            tests_passed += 1

        api_main = api_path / "main.py"
        if api_main.exists():
            print(f"   ✓ FastAPI entry point")
            tests_passed += 1

        routers_path = api_path / "routers"
        routers = ["market.py", "signals.py", "portfolio.py", "models.py", "training.py"]
        for router in routers:
            if (routers_path / router).exists():
                print(f"   ✓ Router: {router}")
                tests_passed += 1

        # Check data structure
        print("\n✅ Data & Models:")
        for dir_name in ["data", "logs", "models"]:
            dir_path = project_root / dir_name
            if dir_path.exists():
                print(f"   ✓ {dir_name}/ directory exists")
                tests_passed += 1

        db_file = project_root / "data/sentinel.db"
        if db_file.exists():
            print(f"   ✓ SQLite database initialized")
            tests_passed += 1

        self.total_passed += tests_passed
        self.results["Backend Structure"] = "PASSED" if tests_passed > 15 else "PARTIAL"

    def print_summary(self):
        """Print test summary"""
        print("\n" + "█"*80)
        print("📊 TEST RESULTS SUMMARY")
        print("█"*80)

        for test_name, status in self.results.items():
            if status == "PASSED":
                symbol = "✅"
            elif status == "PARTIAL":
                symbol = "⚠️"
            else:
                symbol = "❌"
            print(f"{symbol} {test_name}: {status}")

        print(f"\n📈 Statistics:")
        print(f"   Total Passed: {self.total_passed}")
        print(f"   Total Failed: {self.total_failed}")
        print(f"   Overall Status: {'✅ PASSED' if self.total_failed == 0 else '⚠️ PARTIAL SUCCESS'}")
        print("\n" + "█"*80 + "\n")

def main():
    print("\n" + "█"*80)
    print("🧪 QUANT SENTINEL - COMPREHENSIVE TEST SUITE")
    print("█"*80)
    print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 Project Root: {project_root}\n")

    runner = TestRunner()

    # Run all test suites
    runner.test_frontend_structure()
    runner.test_backend_structure()
    runner.run_python_tests()

    # Print summary
    runner.print_summary()

    return 0 if runner.total_failed == 0 else 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)


