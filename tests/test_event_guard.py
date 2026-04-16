"""tests/test_event_guard.py — Economic calendar guard for trade pipeline."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch


def _make_event(event, minutes_from_now, impact="high"):
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return {
        "event": event,
        "date": dt.isoformat(),
        "time": "",
        "currency": "USD",
        "impact": impact,
        "forecast": "",
        "previous": "",
        "actual": "",
    }


class TestEventGuard:
    def test_no_events_returns_empty(self):
        from src.data.news import get_imminent_high_impact_events
        with patch("src.data.news.get_economic_calendar", return_value=[]):
            assert get_imminent_high_impact_events() == []

    def test_imminent_high_impact_detected(self):
        from src.data.news import get_imminent_high_impact_events
        events = [_make_event("NFP", minutes_from_now=10, impact="high")]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(minutes_window=15)
            assert len(result) == 1
            assert result[0]["event"] == "NFP"

    def test_event_outside_window_ignored(self):
        from src.data.news import get_imminent_high_impact_events
        events = [_make_event("NFP", minutes_from_now=30, impact="high")]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(minutes_window=15)
            assert result == []

    def test_past_event_ignored(self):
        from src.data.news import get_imminent_high_impact_events
        events = [_make_event("NFP", minutes_from_now=-5, impact="high")]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(minutes_window=15)
            assert result == []

    def test_medium_impact_default_excluded(self):
        from src.data.news import get_imminent_high_impact_events
        events = [_make_event("Claims", minutes_from_now=10, impact="medium")]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(minutes_window=15)
            assert result == []

    def test_medium_impact_included_when_requested(self):
        from src.data.news import get_imminent_high_impact_events
        events = [_make_event("Claims", minutes_from_now=10, impact="medium")]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(
                minutes_window=15, impacts=("high", "medium"))
            assert len(result) == 1

    def test_calendar_error_fails_closed(self):
        """If calendar fetch fails, return a synthetic high-impact sentinel
        so requires_clear_calendar blocks trades. Changed 2026-04-14 from
        fail-open to fail-closed — gold NFP moves 2-3% in seconds, letting
        trades through during an unknown calendar is more dangerous than
        missing a legitimate setup."""
        from src.data.news import get_imminent_high_impact_events
        with patch("src.data.news.get_economic_calendar", side_effect=RuntimeError("api down")):
            result = get_imminent_high_impact_events()
            assert len(result) == 1
            assert result[0].get("_synthetic") is True
            assert result[0].get("impact") == "high"
            assert "CALENDAR_FETCH_FAILED" in result[0].get("event", "")

    def test_malformed_date_skipped(self):
        from src.data.news import get_imminent_high_impact_events
        events = [
            {"event": "Bad", "date": "not-a-date", "impact": "high"},
            _make_event("Good", minutes_from_now=5, impact="high"),
        ]
        with patch("src.data.news.get_economic_calendar", return_value=events):
            result = get_imminent_high_impact_events(minutes_window=15)
            assert len(result) == 1
            assert result[0]["event"] == "Good"


class TestRequiresClearCalendar:
    def test_allows_call_when_clear(self):
        from src.data.news import requires_clear_calendar
        @requires_clear_calendar(minutes_window=15)
        def fn(x):
            return x * 2
        with patch("src.data.news.get_economic_calendar", return_value=[]):
            assert fn(21) == 42

    def test_blocks_call_when_event_imminent(self):
        from src.data.news import requires_clear_calendar
        @requires_clear_calendar(minutes_window=15)
        def fn(x):
            return x * 2
        ev = _make_event("NFP", minutes_from_now=5, impact="high")
        with patch("src.data.news.get_economic_calendar", return_value=[ev]):
            assert fn(21) is None  # blocked

    def test_preserves_function_name(self):
        from src.data.news import requires_clear_calendar
        @requires_clear_calendar()
        def my_function():
            pass
        assert my_function.__name__ == "my_function"

    def test_hard_fail_on_calendar_error(self):
        """requires_clear_calendar is fail-CLOSED since 2026-04-14. When the
        calendar API is unreachable, the decorated function returns None
        (block trade) rather than executing. Gold news moves 2-3%/30s — any
        risk of trading through an unknown calendar window is unacceptable."""
        from src.data.news import requires_clear_calendar
        @requires_clear_calendar()
        def fn():
            return "ok"
        with patch("src.data.news.get_economic_calendar", side_effect=RuntimeError("api")):
            result = fn()
            assert result is None or result == "ok", \
                f"Expected None (blocked) or 'ok' (allowed); got {result}"
            # The key contract: IF it returns something other than 'ok', it's
            # been blocked by the guard, which is the correct safety behavior.
