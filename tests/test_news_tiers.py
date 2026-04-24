"""tests/test_news_tiers.py — Event tier classifier (src/data/news.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.news import classify_event_tier  # noqa: E402


class TestClassifyEventTier:
    def test_tier1_nfp(self):
        assert classify_event_tier("Non-Farm Payrolls") == "tier1"
        assert classify_event_tier("nfp m/m") == "tier1"

    def test_tier1_cpi(self):
        assert classify_event_tier("CPI m/m") == "tier1"
        assert classify_event_tier("Core CPI y/y") == "tier1"

    def test_tier1_fomc(self):
        assert classify_event_tier("FOMC Statement") == "tier1"
        assert classify_event_tier("FOMC Minutes") == "tier1"
        assert classify_event_tier("Federal Funds Rate") == "tier1"

    def test_tier1_pce(self):
        assert classify_event_tier("Core PCE Price Index") == "tier1"
        assert classify_event_tier("PCE m/m") == "tier1"

    def test_tier2_ppi(self):
        assert classify_event_tier("PPI m/m") == "tier2"
        assert classify_event_tier("Producer Prices") == "tier2"

    def test_tier2_adp(self):
        assert classify_event_tier("ADP Employment Change") == "tier2"
        assert classify_event_tier("Nonfarm Employment Change") == "tier2"

    def test_tier2_other(self):
        assert classify_event_tier("Retail Sales m/m") == "tier2"
        assert classify_event_tier("Initial Jobless Claims") == "tier2"
        assert classify_event_tier("GDP q/q") == "tier2"
        assert classify_event_tier("Unemployment Rate") == "tier2"

    def test_tier3_speakers(self):
        assert classify_event_tier("Powell Speaks") == "tier3"
        assert classify_event_tier("Fed Chair Speech") == "tier3"
        assert classify_event_tier("ECB President Lagarde") == "tier3"
        assert classify_event_tier("BoJ Press Conference") == "tier3"

    def test_unrecognized_events_return_none(self):
        assert classify_event_tier("Factory Orders") is None
        assert classify_event_tier("Leading Indicators") is None
        assert classify_event_tier("Business Inventories") is None
        assert classify_event_tier("") is None
        assert classify_event_tier(None) is None

    def test_case_insensitive(self):
        assert classify_event_tier("NON-FARM PAYROLLS") == "tier1"
        assert classify_event_tier("non-farm payrolls") == "tier1"
        assert classify_event_tier("Non-Farm Payrolls m/m") == "tier1"

    def test_partial_substring_match(self):
        # Longer strings that contain keyword substrings
        assert classify_event_tier("US CPI m/m released") == "tier1"
        assert classify_event_tier("Surprise FOMC announcement") == "tier1"
