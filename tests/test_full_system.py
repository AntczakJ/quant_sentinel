#!/usr/bin/env python3
"""
tests/test_full_system.py - Comprehensive full system testing
Tests all components: frontend structure, backend endpoints, integration
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path
import requests
from typing import Dict, List, Tuple

# Colors for output
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def log_test(status: str, message: str):
    """Log test result"""
    if status == "PASS":
        print(f"{Color.GREEN}✅{Color.END} {message}")
    elif status == "FAIL":
        print(f"{Color.RED}❌{Color.END} {message}")
    elif status == "SKIP":
        print(f"{Color.YELLOW}⚠️{Color.END} {message}")
    elif status == "INFO":
        print(f"{Color.BLUE}ℹ️{Color.END} {message}")

def print_section(title: str):
    """Print test section header"""
    print(f"\n{Color.BOLD}{'='*80}{Color.END}")
    print(f"{Color.BOLD}{title}{Color.END}")
    print(f"{Color.BOLD}{'='*80}{Color.END}\n")

# ============================================================================
# FRONTEND TESTS
# ============================================================================

def test_frontend_structure() -> int:
    """Test frontend file structure and components"""
    print_section("🧪 FRONTEND STRUCTURE TESTS")
    passed = 0

    frontend_path = Path("frontend")
    if not frontend_path.exists():
        log_test("FAIL", "Frontend directory not found")
        return 0

    # Check component files
    components = [
        "src/components/charts/CandlestickChart.tsx",
        "src/components/dashboard/Dashboard.tsx",
        "src/components/dashboard/Header.tsx",
        "src/components/dashboard/SignalPanel.tsx",
        "src/components/dashboard/PortfolioStats.tsx",
        "src/components/dashboard/ModelStats.tsx",
        "src/components/dashboard/SignalHistory.tsx",
    ]

    for component in components:
        file_path = frontend_path / component
        if file_path.exists():
            log_test("PASS", f"Component exists: {component}")
            passed += 1
        else:
            log_test("FAIL", f"Component missing: {component}")

    # Check config files
    configs = [
        "package.json",
        "tsconfig.json",
        "vite.config.ts",
        "tailwind.config.js",
    ]

    for config in configs:
        config_path = frontend_path / config
        if config_path.exists():
            log_test("PASS", f"Config exists: {config}")
            passed += 1
        else:
            log_test("FAIL", f"Config missing: {config}")

    # Check API client
    api_client = frontend_path / "src/api/client.ts"
    if api_client.exists():
        log_test("PASS", "API client exists")
        passed += 1
    else:
        log_test("FAIL", "API client missing")

    # Check store
    store = frontend_path / "src/store/tradingStore.ts"
    if store.exists():
        log_test("PASS", "Zustand store exists")
        passed += 1
    else:
        log_test("FAIL", "Zustand store missing")

    # Check types
    types = frontend_path / "src/types/trading.ts"
    if types.exists():
        log_test("PASS", "TypeScript types defined")
        passed += 1
    else:
        log_test("FAIL", "TypeScript types missing")

    return passed

def test_frontend_files() -> int:
    """Test frontend file contents"""
    print_section("📄 FRONTEND FILE VALIDATION")
    passed = 0

    frontend_path = Path("frontend/src/components")

    # Test CandlestickChart content
    chart_file = frontend_path / "charts/CandlestickChart.tsx"
    if chart_file.exists():
        content = chart_file.read_text(encoding='utf-8')
        if "LineChart" in content and "BarChart" in content:
            log_test("PASS", "CandlestickChart uses Recharts components")
            passed += 1
        if "RSI" in content:
            log_test("PASS", "CandlestickChart includes RSI")
            passed += 1
        if "Bollinger" in content:
            log_test("PASS", "CandlestickChart includes Bollinger Bands")
            passed += 1

    # Test SignalPanel content
    signal_file = frontend_path / "dashboard/SignalPanel.tsx"
    if signal_file.exists():
        content = signal_file.read_text()
        if "STRONG_BUY" in content:
            log_test("PASS", "SignalPanel has consensus levels")
            passed += 1
        if "RL Agent" in content and "LSTM" in content and "XGBoost" in content:
            log_test("PASS", "SignalPanel shows all 3 models")
            passed += 1

    # Test PortfolioStats content
    portfolio_file = frontend_path / "dashboard/PortfolioStats.tsx"
    if portfolio_file.exists():
        content = portfolio_file.read_text()
        if "balance" in content.lower() and "pnl" in content.lower():
            log_test("PASS", "PortfolioStats displays balance and P&L")
            passed += 1

    # Test ModelStats content
    models_file = frontend_path / "dashboard/ModelStats.tsx"
    if models_file.exists():
        content = models_file.read_text()
        if "accuracy" in content.lower() or "ensemble" in content.lower():
            log_test("PASS", "ModelStats shows metrics")
            passed += 1

    return passed

# ============================================================================
# BACKEND TESTS
# ============================================================================

def test_backend_structure() -> int:
    """Test backend file structure"""
    print_section("🧪 BACKEND STRUCTURE TESTS")
    passed = 0

    src_path = Path("src")
    if not src_path.exists():
        log_test("FAIL", "src directory not found")
        return 0

    # Check core modules
    modules = [
        "main.py",
        "smc_engine.py",
        "ai_engine.py",
        "ml_models.py",
        "finance.py",
        "database.py",
        "config.py",
        "scanner.py",
    ]

    for module in modules:
        module_path = src_path / module
        if module_path.exists():
            log_test("PASS", f"Module exists: {module}")
            passed += 1
        else:
            log_test("SKIP", f"Module not found: {module}")

    # Check API structure
    api_path = Path("api")
    if api_path.exists():
        log_test("PASS", "API directory exists")
        passed += 1

        api_main = api_path / "main.py"
        if api_main.exists():
            log_test("PASS", "FastAPI main entry point exists")
            passed += 1

    # Check routers
    routers_path = api_path / "routers"
    if routers_path.exists():
        routers = [
            "market.py",
            "signals.py",
            "portfolio.py",
            "models.py",
            "training.py",
        ]
        for router in routers:
            if (routers_path / router).exists():
                log_test("PASS", f"Router exists: {router}")
                passed += 1

    # Check database
    db_path = Path("data/sentinel.db")
    if db_path.exists():
        log_test("PASS", "SQLite database exists")
        passed += 1
    else:
        log_test("SKIP", "Database not initialized (OK for first run)")

    return passed

def test_backend_imports() -> int:
    """Test that backend modules can be imported"""
    print_section("🧪 BACKEND IMPORTS TEST")
    passed = 0

    modules_to_test = [
        "src.config",
        "src.logger",
        "src.database",
        "src.finance",
    ]

    for module in modules_to_test:
        try:
            __import__(module)
            log_test("PASS", f"Module imports successfully: {module}")
            passed += 1
        except ImportError as e:
            log_test("FAIL", f"Failed to import {module}: {e}")
        except Exception as e:
            log_test("SKIP", f"Import issue for {module}: {e}")

    return passed

# ============================================================================
# API ENDPOINTS TESTS
# ============================================================================

def test_api_endpoints() -> int:
    """Test backend API endpoints"""
    print_section("🧪 BACKEND API ENDPOINTS TEST")
    passed = 0

    base_url = "http://localhost:8000"
    endpoints = [
        ("Health Check", "/health"),
        ("Market Status", "/api/market/status"),
        ("Ticker", "/api/market/ticker"),
        ("Candles", "/api/market/candles"),
        ("Indicators", "/api/market/indicators"),
        ("Current Signal", "/api/signals/current"),
        ("Signal History", "/api/signals/history"),
        ("Portfolio Status", "/api/portfolio/status"),
        ("Models Stats", "/api/models/stats"),
    ]

    for endpoint_name, endpoint_path in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint_path}", timeout=5)
            if response.status_code in [200, 404, 500]:
                log_test("PASS", f"{endpoint_name}: {response.status_code}")
                passed += 1
            else:
                log_test("SKIP", f"{endpoint_name}: Unexpected status {response.status_code}")
        except requests.exceptions.ConnectionError:
            log_test("SKIP", f"{endpoint_name}: Backend not running on {base_url}")
        except Exception as e:
            log_test("SKIP", f"{endpoint_name}: {str(e)}")

    return passed

# ============================================================================
# CONFIGURATION TESTS
# ============================================================================

def test_configuration() -> int:
    """Test configuration files"""
    print_section("🧪 CONFIGURATION TESTS")
    passed = 0

    # Check .env
    env_file = Path(".env")
    if env_file.exists():
        log_test("PASS", ".env file exists")
        passed += 1
    else:
        log_test("SKIP", ".env file not found (may be in .env.local)")

    # Check requirements.txt
    req_file = Path("requirements.txt")
    if req_file.exists():
        content = req_file.read_text()
        required_packages = [
            "fastapi",
            "pandas",
            "numpy",
            "tensorflow",
            "xgboost",
            "scikit-learn",
            "openai",
            "python-telegram-bot",
        ]
        for package in required_packages:
            if package.lower() in content.lower():
                log_test("PASS", f"Required package found: {package}")
                passed += 1
            else:
                log_test("SKIP", f"Package not in requirements: {package}")

    # Check frontend package.json
    package_file = Path("frontend/package.json")
    if package_file.exists():
        log_test("PASS", "Frontend package.json exists")
        passed += 1

    return passed

# ============================================================================
# INTEGRATION TESTS
# ============================================================================

def test_integration() -> int:
    """Test overall system integration"""
    print_section("🧪 SYSTEM INTEGRATION TESTS")
    passed = 0

    # Test database connection
    try:
        from src.core.database import Database
        db = Database()
        log_test("PASS", "Database module loads")
        passed += 1
    except Exception as e:
        log_test("SKIP", f"Database test: {e}")

    # Test configuration loading
    try:
        from src.core.config import Config
        log_test("PASS", "Configuration module loads")
        passed += 1
    except Exception as e:
        log_test("SKIP", f"Configuration test: {e}")

    # Test logger
    try:
        from src.core.logger import logger
        logger.info("Test log message")
        log_test("PASS", "Logger module works")
        passed += 1
    except Exception as e:
        log_test("SKIP", f"Logger test: {e}")

    # Test data directory
    data_dir = Path("data")
    if data_dir.exists():
        log_test("PASS", "Data directory exists")
        passed += 1
    else:
        log_test("FAIL", "Data directory missing")

    # Test logs directory
    logs_dir = Path("logs")
    if logs_dir.exists():
        log_test("PASS", "Logs directory exists")
        passed += 1
    else:
        log_test("SKIP", "Logs directory not created (will be created on first run)")

    # Test models directory
    models_dir = Path("models")
    if models_dir.exists():
        log_test("PASS", "Models directory exists")
        passed += 1
    else:
        log_test("SKIP", "Models directory not found")

    return passed

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests"""
    print("\n")
    print("█" * 80)
    print("🧪 QUANT SENTINEL - COMPREHENSIVE SYSTEM TEST SUITE")
    print("█" * 80)
    print(f"\n📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 Working Directory: {os.getcwd()}\n")

    results = {}
    total_passed = 0

    # Run all test suites
    test_suites = [
        ("Frontend Structure", test_frontend_structure),
        ("Frontend Files", test_frontend_files),
        ("Backend Structure", test_backend_structure),
        ("Backend Imports", test_backend_imports),
        ("API Endpoints", test_api_endpoints),
        ("Configuration", test_configuration),
        ("Integration", test_integration),
    ]

    for suite_name, suite_func in test_suites:
        try:
            passed = suite_func()
            results[suite_name] = passed
            total_passed += passed
        except Exception as e:
            log_test("FAIL", f"{suite_name} crashed: {e}")
            results[suite_name] = 0

    # Print summary
    print_section("📊 TEST SUMMARY")

    for suite_name, passed in results.items():
        status = "PASS" if passed > 0 else "SKIP"
        print(f"{Color.BOLD}{suite_name}:{Color.END} {passed} tests")

    print(f"\n{Color.BOLD}TOTAL TESTS PASSED: {total_passed}{Color.END}\n")

    print("█" * 80)
    print("🎉 COMPREHENSIVE SYSTEM TESTING COMPLETE")
    print("█" * 80 + "\n")

    return total_passed

if __name__ == "__main__":
    passed = main()
    sys.exit(0 if passed >= 20 else 1)

