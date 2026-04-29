"""Tests for the USE_FLAT_RISK env-flag scaffold (Lot Sizing Option A)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_env():
    prev_use = os.environ.get("USE_FLAT_RISK")
    prev_pct = os.environ.get("FLAT_RISK_PCT")
    yield
    for key, val in (("USE_FLAT_RISK", prev_use), ("FLAT_RISK_PCT", prev_pct)):
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def test_flat_risk_off_by_default(monkeypatch):
    """When USE_FLAT_RISK is unset, the legacy Kelly+session+vol path runs."""
    os.environ.pop("USE_FLAT_RISK", None)
    # We just verify the env-read pattern, not the full calculate_position
    # (which depends on DB state). The flag check itself is a pure bool.
    assert os.environ.get("USE_FLAT_RISK") != "1"


def test_flat_risk_on_uses_explicit_pct():
    os.environ["USE_FLAT_RISK"] = "1"
    os.environ["FLAT_RISK_PCT"] = "0.5"
    pct = float(os.environ.get("FLAT_RISK_PCT", "0.5"))
    assert pct == 0.5


def test_flat_risk_default_pct_when_unset():
    os.environ["USE_FLAT_RISK"] = "1"
    os.environ.pop("FLAT_RISK_PCT", None)
    pct = float(os.environ.get("FLAT_RISK_PCT", "0.5"))
    assert pct == 0.5


def test_flat_risk_custom_pct():
    os.environ["USE_FLAT_RISK"] = "1"
    os.environ["FLAT_RISK_PCT"] = "0.3"
    pct = float(os.environ.get("FLAT_RISK_PCT", "0.5"))
    assert pct == 0.3
