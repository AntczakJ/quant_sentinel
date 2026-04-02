#!/usr/bin/env python3
"""tests/conftest.py - Pytest configuration and fixtures"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture
def db():
    """Database fixture"""
    from src.database import NewsDB
    return NewsDB()

@pytest.fixture
def config():
    """Config fixture"""
    from src import config
    return config

@pytest.fixture
def logger():
    """Logger fixture"""
    from src.logger import logger
    return logger

@pytest.fixture
def sample_analysis():
    """Sample SMC analysis data"""
    return {
        'price': 2545.50,
        'rsi': 45.0,
        'trend': 'bull',
        'fvg_type': 'bullish',
        'ob_price': 2540.00,
        'swing_high': 2550.00,
        'swing_low': 2530.00,
        'atr': 15.0,
        'macro_regime': 'zielony',
    }

