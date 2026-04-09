"""
tests/test_news.py — Tests for news pipeline (Finnhub, FAISS similarity)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNewsFeed:
    def test_gold_keyword_detection(self):
        from src.data.news_feed import _is_gold_relevant
        assert _is_gold_relevant("Gold surges amid inflation fears") is True
        assert _is_gold_relevant("Fed raises interest rates") is True
        assert _is_gold_relevant("Apple reports quarterly earnings") is False
        assert _is_gold_relevant("XAU/USD hits new high") is True
        assert _is_gold_relevant("Dollar strengthens against euro") is True

    def test_headline_classification(self):
        from src.data.news_feed import _classify_headline
        bullish = _classify_headline("Gold surges as safe haven demand rises amid war")
        assert bullish["score"] > 0
        assert bullish["impact"] == "high"

        bearish = _classify_headline("Strong jobs report pushes dollar higher gold drops")
        assert bearish["score"] < 0

        neutral = _classify_headline("Markets await data release")
        assert neutral["impact"] == "low"

    def test_get_gold_news_signal(self):
        from src.data.news_feed import get_gold_news_signal
        result = get_gold_news_signal()
        assert isinstance(result, dict)
        assert "signal" in result
        assert "news_count" in result
        assert result["signal"] in (-1, 0, 1)


class TestNewsSimilarity:
    def test_find_similar_returns_dict(self):
        from src.data.news_similarity import find_similar_news
        result = find_similar_news("Federal Reserve holds interest rates steady")
        assert isinstance(result, dict)
        assert "signal" in result

    def test_build_index(self):
        from src.data.news_similarity import build_index_from_finnhub
        count = build_index_from_finnhub()
        assert isinstance(count, int)
        assert count >= 0
