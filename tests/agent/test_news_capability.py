"""Tests for the `news` capability handler."""

import pytest

from TerraFin.agent.service import TerraFinAgentService
from TerraFin.data.contracts.news import NewsFeed, NewsItem


class _FakeFactory:
    def __init__(self, feed: NewsFeed) -> None:
        self.feed = feed
        self.calls: list[tuple] = []

    def get_news(self, query: str, *, days: int = 7, limit: int = 25) -> NewsFeed:
        self.calls.append((query, days, limit))
        return self.feed


def _feed() -> NewsFeed:
    return NewsFeed(
        query="NVDA",
        days=7,
        items=[
            NewsItem(
                title="Nvidia beats on revenue - Reuters",
                published_at="2026-08-03",
                url="https://news.google.com/rss/articles/ABC",
                source="Reuters",
                source_url="https://www.reuters.com",
                query="NVDA",
            )
        ],
        warnings=["95 headlines matched; returning the 1 most recent"],
    )


def test_news_returns_headline_metadata() -> None:
    factory = _FakeFactory(_feed())
    payload = TerraFinAgentService(data_factory=factory).news("NVDA", days=7, limit=1)

    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["headline"] == "Nvidia beats on revenue", "publisher suffix should be stripped"
    assert item["title"].endswith("- Reuters"), "raw title stays available"
    assert item["source"] == "Reuters"
    assert item["url"].startswith("https://news.google.com/rss/articles/")
    assert payload["processing"]["sourceVersion"] == "news-google-rss"


def test_truncation_warning_is_passed_through() -> None:
    payload = TerraFinAgentService(data_factory=_FakeFactory(_feed())).news("NVDA")

    assert any("most recent" in warning for warning in payload["warnings"])


def test_query_overrides_ticker() -> None:
    factory = _FakeFactory(_feed())
    TerraFinAgentService(data_factory=factory).news("NVDA", query="Nvidia earnings", days=14, limit=5)

    assert factory.calls == [("Nvidia earnings", 14, 5)]


def test_ticker_is_used_when_no_query_given() -> None:
    factory = _FakeFactory(_feed())
    TerraFinAgentService(data_factory=factory).news("nvda")

    assert factory.calls[0][0] == "nvda"


def test_missing_ticker_and_query_is_rejected() -> None:
    service = TerraFinAgentService(data_factory=_FakeFactory(_feed()))

    with pytest.raises(ValueError, match="Either ticker or query is required"):
        service.news()


def test_empty_feed_is_not_an_error() -> None:
    empty = NewsFeed(query="NVDA", days=7, items=[], warnings=["news source unavailable"])
    payload = TerraFinAgentService(data_factory=_FakeFactory(empty)).news("NVDA")

    assert payload["count"] == 0
    assert payload["items"] == []
    assert payload["warnings"] == ["news source unavailable"]
