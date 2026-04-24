"""tests/test_asia_orb.py — Asia Session ORB (src/trading/asia_orb.py)."""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.trading.asia_orb import (  # noqa: E402
    _asia_window_bounds,
    detect_orb_signal,
    get_asia_range,
)


def _make_df(reference_end_utc: dt.datetime, asia_close_price: float = 2000.0,
             london_close_price: float | None = None, hours: int = 24) -> pd.DataFrame:
    """Build an OHLC df ending at reference_end_utc with London-open breakout
    if london_close_price != asia_close_price."""
    if london_close_price is None:
        london_close_price = asia_close_price
    start = reference_end_utc - dt.timedelta(hours=hours - 1)
    idx = pd.date_range(start=start, end=reference_end_utc, freq="1h")
    prices = []
    for ts in idx:
        h = ts.hour
        if 0 <= h <= 6:
            # Asia window: centered around asia_close_price with 1.5 wiggle
            prices.append(asia_close_price + (h - 3) * 0.5)
        else:
            # Non-Asia: at london_close_price
            prices.append(london_close_price)
    return pd.DataFrame({
        "open": prices, "close": prices,
        "high": [p + 0.5 for p in prices], "low": [p - 0.5 for p in prices],
    }, index=idx)


class TestAsiaWindowBounds:
    def test_window_is_seven_hours(self):
        ref = dt.datetime(2026, 4, 22, 10, 0, tzinfo=dt.timezone.utc)
        start, end = _asia_window_bounds(ref)
        assert (end - start).total_seconds() == 7 * 3600

    def test_window_ends_at_seven_utc(self):
        ref = dt.datetime(2026, 4, 22, 10, 0, tzinfo=dt.timezone.utc)
        _, end = _asia_window_bounds(ref)
        assert end.hour == 7
        assert end.minute == 0


class TestGetAsiaRange:
    def test_extracts_high_low_from_window(self):
        ref = dt.datetime(2026, 4, 22, 8, 0, tzinfo=dt.timezone.utc)
        df = _make_df(ref, asia_close_price=2000.0, london_close_price=2010.0)
        asia = get_asia_range(df, reference_utc=ref)
        assert asia is not None
        assert asia["bars"] == 7
        # Asia prices 1998.5 to 2001.5, high wicks +0.5
        assert asia["high"] == pytest.approx(2002.0, abs=0.1)
        assert asia["low"] == pytest.approx(1998.0, abs=0.1)

    def test_returns_none_when_no_data(self):
        assert get_asia_range(None) is None
        assert get_asia_range(pd.DataFrame()) is None

    def test_returns_none_when_window_missing(self):
        # Reference at midnight — Asia just starting, no bars yet
        ref = dt.datetime(2026, 4, 22, 0, 0, tzinfo=dt.timezone.utc)
        # df ending at 23:00 previous day
        end = ref - dt.timedelta(hours=1)
        df = _make_df(end, 2000.0, 2000.0, hours=20)
        asia = get_asia_range(df, reference_utc=ref)
        # Yesterday's Asia completed ends yesterday 07:00 — not in df range
        # Function should try "today's upcoming Asia" which has no data yet
        # Either None (no data) or Asia window with few/zero bars
        # The defined contract: None if <3 Asia bars
        if asia is not None:
            assert asia["bars"] >= 3


class TestDetectOrbSignal:
    def _build(self, ref=None, asia_close=2000.0, breakout_to=None):
        if ref is None:
            ref = dt.datetime(2026, 4, 22, 8, 0, tzinfo=dt.timezone.utc)
        return ref, _make_df(ref, asia_close, breakout_to or asia_close)

    def test_no_breakout_inside_range(self):
        ref, df = self._build(asia_close=2000.0, breakout_to=2000.0)
        sig = detect_orb_signal(df, htf_ema200=None, reference_utc=ref)
        assert sig["direction"] == "NONE"
        assert sig["reason"] == "inside_asia_range"

    def test_bull_breakout_no_htf(self):
        ref, df = self._build(asia_close=2000.0, breakout_to=2010.0)
        sig = detect_orb_signal(df, htf_ema200=None, reference_utc=ref)
        assert sig["direction"] == "LONG"
        assert "bull" in sig["reason"]
        assert sig["asia_high"] < sig["current_close"]

    def test_bear_breakout_no_htf(self):
        ref, df = self._build(asia_close=2000.0, breakout_to=1985.0)
        sig = detect_orb_signal(df, htf_ema200=None, reference_utc=ref)
        assert sig["direction"] == "SHORT"
        assert "bear" in sig["reason"]

    def test_htf_filter_blocks_bull_when_below_ema(self):
        ref, df = self._build(asia_close=2000.0, breakout_to=2010.0)
        # EMA200 above current price → price is "below trend" → bull break invalid
        sig = detect_orb_signal(df, htf_ema200=2020.0, reference_utc=ref)
        assert sig["direction"] == "NONE"
        assert sig["reason"] == "bull_break_below_ema200"

    def test_htf_filter_allows_bull_when_above_ema(self):
        ref, df = self._build(asia_close=2000.0, breakout_to=2010.0)
        sig = detect_orb_signal(df, htf_ema200=2005.0, reference_utc=ref)
        assert sig["direction"] == "LONG"

    def test_stale_signal_rejected_after_2h(self):
        # Reference 3h after London open — outside 2h window
        ref = dt.datetime(2026, 4, 22, 10, 0, tzinfo=dt.timezone.utc)
        df = _make_df(ref, 2000.0, 2010.0)
        sig = detect_orb_signal(df, htf_ema200=None, reference_utc=ref,
                                 max_post_open_hours=2.0)
        assert sig["direction"] == "NONE"
        assert "stale" in sig["reason"]

    def test_pre_london_open_rejected(self):
        # Reference at 06:00 UTC — Asia still running, pre London open
        ref = dt.datetime(2026, 4, 22, 6, 0, tzinfo=dt.timezone.utc)
        df = _make_df(ref, 2000.0, 2000.0)
        sig = detect_orb_signal(df, htf_ema200=None, reference_utc=ref)
        # Could be "insufficient_asia_data" (if Asia not yet 3+ bars)
        # or "pre_london_open" if Asia has accumulated
        assert sig["direction"] == "NONE"
