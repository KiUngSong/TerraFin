"""Tests for the Google News RSS headline provider and contract."""

import json
from datetime import date

import pytest

from TerraFin.data.contracts.news import NewsFeed, NewsItem
from TerraFin.data.providers.corporate import news as news_module


_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Nvidia beats on data-centre revenue - Reuters</title>
    <link>https://news.google.com/rss/articles/ABC123</link>
    <pubDate>Mon, 03 Aug 2026 12:00:00 GMT</pubDate>
    <source url="https://www.reuters.com">Reuters</source>
  </item>
  <item>
    <title>Older story - CNBC</title>
    <link>https://news.google.com/rss/articles/DEF456</link>
    <pubDate>Sat, 01 Aug 2026 08:30:00 GMT</pubDate>
    <source url="https://www.cnbc.com">CNBC</source>
  </item>
  <item>
    <title>No date here</title>
  </item>
</channel></rss>
"""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    """Serve a fixed feed, and point the file cache at a temp dir.

    `get_news` reads through `CacheManager`'s static file cache, which roots at
    Path.home() — without redirecting it a test would be served whatever the
    developer's real cache holds, and would pollute it.
    """

    from TerraFin.data.cache import manager as cache_manager

    monkeypatch.setattr(cache_manager, "_FILE_CACHE_DIR", tmp_path / "cache")
    # The provider keeps module-level single-flight locks and a short failure
    # memo; leaving either populated would leak between tests.
    monkeypatch.setattr(news_module, "_fetch_locks", {})
    monkeypatch.setattr(news_module, "_lock_refs", {})
    monkeypatch.setattr(news_module, "_recent_failures", {})

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(news_module.urllib.request, "urlopen", lambda *a, **k: _Response(_FEED.encode()))


def test_fetch_payload_is_json_safe_and_skips_bad_items() -> None:
    raw = news_module._fetch_raw("NVDA", 7)

    assert json.loads(json.dumps(raw)) == raw, "payload must survive the cache's JSON round-trip"
    assert len(raw["records"]) == 2, "the item with no date must be skipped"
    assert any("skipped" in warning for warning in raw["warnings"])
    assert raw["records"][0]["source"] == "Reuters"
    assert raw["records"][0]["sourceUrl"] == "https://www.reuters.com"


def test_get_news_sorts_newest_first_and_keeps_provenance() -> None:
    feed = news_module.get_news("NVDA", days=7, limit=10)

    assert [item.published_at for item in feed.items] == ["2026-08-03", "2026-08-01"]
    first = feed.items[0]
    assert first.source == "Reuters"
    assert first.url == "https://news.google.com/rss/articles/ABC123"
    assert first.query == "NVDA"


def test_limit_truncation_is_reported() -> None:
    feed = news_module.get_news("NVDA", days=7, limit=1)

    assert len(feed.items) == 1
    assert any("returning the 1 most recent" in warning for warning in feed.warnings)


def test_headline_strips_the_publisher_suffix() -> None:
    item = NewsItem(title="Nvidia beats on revenue - Reuters", published_at="2026-08-03", source="Reuters")

    assert item.headline == "Nvidia beats on revenue"


def test_headline_left_alone_without_a_source() -> None:
    item = NewsItem(title="Nvidia beats on revenue - Reuters", published_at="2026-08-03")

    assert item.headline == "Nvidia beats on revenue - Reuters"


def test_contract_rejects_malformed_dates() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        NewsItem(title="x", published_at="03 Aug 2026")
    with pytest.raises(ValueError, match="title is required"):
        NewsItem(title="", published_at="2026-08-03")


def test_argument_validation() -> None:
    with pytest.raises(ValueError, match="Query is required"):
        news_module.get_news("  ")
    with pytest.raises(ValueError, match="days must be"):
        news_module.get_news("NVDA", days=0)
    with pytest.raises(ValueError, match="limit must be"):
        news_module.get_news("NVDA", limit=999)


def test_as_of_anchors_the_window_and_keys_the_cache() -> None:
    """A historical window must not share a cache entry with the trailing one."""

    trailing = news_module._cache_key("NVDA", 8, None)
    historical = news_module._cache_key("NVDA", 8, "2026-07-01")

    assert trailing != historical

    url = news_module._build_url("NVDA", days=8, as_of=date(2026, 7, 1))
    assert "after%3A2026-06-23" in url and "before%3A2026-07-02" in url


def test_fetch_raises_instead_of_returning_an_empty_feed(monkeypatch) -> None:
    """A failure must not be cacheable.

    Returning an empty dict here would be written to the cache as a success and
    pin "no news" for a full TTL, so a re-run would reproduce the blank.
    """

    def explode(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    with pytest.raises(news_module.NewsUnavailableError, match="fetch failed"):
        news_module._fetch_raw("NVDA", 7)


def test_get_news_reports_a_failure_without_caching_it(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    feed = news_module.get_news("NVDA", days=7)

    assert feed.items == []
    assert any("fetch failed" in warning for warning in feed.warnings)


def test_stale_headlines_are_served_when_the_feed_breaks(monkeypatch) -> None:
    fresh = news_module.get_news("NVDA", days=7)
    assert len(fresh.items) == 2, "prime the cache first"

    # Expire the entry, then break the feed: stale beats nothing, but must say so.
    monkeypatch.setattr(news_module, "ttl_for", lambda _key: 0)

    def explode(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    degraded = news_module.get_news("NVDA", days=7)

    assert len(degraded.items) == 2
    assert any("stale" in warning for warning in degraded.warnings)


def test_cache_key_does_not_collide_on_spaces_versus_underscores() -> None:
    """Slugifying the query collided; hashing it does not."""

    spaced = news_module._cache_key("AAPL earnings", 7, None)
    underscored = news_module._cache_key("AAPL_earnings", 7, None)

    assert spaced != underscored
    assert news_module._cache_key("AAPL earnings", 7, None) == spaced, "key must be stable"
    assert news_module._cache_key("aapl earnings", 7, None) == spaced, "case-insensitive by design"


def test_cache_key_is_short_for_any_query_length() -> None:
    key = news_module._cache_key("a" * 5000, 7, None)

    assert len(key) < 64, "an unbounded query previously produced a filename over the 255-byte limit"


def test_overlong_query_is_rejected_with_a_clear_error() -> None:
    with pytest.raises(ValueError, match="at most 200 characters"):
        news_module.get_news("a" * 201)


def test_empty_feed_helper() -> None:
    empty = NewsFeed.make_empty("NVDA", 7)

    assert len(empty) == 0
    assert list(empty) == []


def test_concurrent_identical_queries_fetch_once() -> None:
    """Single-flight: N concurrent misses on one key must not fire N fetches.

    `CacheManager.get_payload` serialises misses for a registered source, but the
    static file-cache path does not, so this has to be done here.
    """

    import threading
    from concurrent.futures import ThreadPoolExecutor

    calls: list[str] = []
    barrier = threading.Barrier(6)

    real_fetch = news_module._fetch_raw

    def counting_fetch(query, days, as_of=None):
        calls.append(query)
        return real_fetch(query, days, as_of)

    news_module._fetch_raw = counting_fetch
    try:

        def racer(_):
            barrier.wait()  # maximise overlap on the miss path
            return news_module.get_news("NVDA", days=7)

        with ThreadPoolExecutor(max_workers=6) as pool:
            feeds = list(pool.map(racer, range(6)))
    finally:
        news_module._fetch_raw = real_fetch

    assert len(calls) == 1, f"expected one upstream fetch, got {len(calls)}"
    assert all(len(feed.items) == 2 for feed in feeds), "every caller must get the full feed"


def test_fetched_at_is_carried_through_the_cache(monkeypatch) -> None:
    """The vintage must come from the cached entry, not from today's date.

    Asserting `fresh == cached` cannot fail while both are today, so the fetch
    date is pinned to a fixed past day first.
    """

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 1)

    monkeypatch.setattr(news_module, "date", _FixedDate)
    fresh = news_module.get_news("NVDA", days=7)
    assert fresh.fetched_at == "2026-07-01"

    # Move the clock on; a cached read must still report when it was fetched.
    class _LaterDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 9)

    monkeypatch.setattr(news_module, "date", _LaterDate)
    cached = news_module.get_news("NVDA", days=7)

    assert cached.fetched_at == "2026-07-01", "a cached read must not restamp itself with today"


def test_stale_feed_reports_its_original_vintage(monkeypatch) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 1)

    monkeypatch.setattr(news_module, "date", _FixedDate)
    primed = news_module.get_news("NVDA", days=7)
    assert primed.fetched_at == "2026-07-01"

    # Expire the entry and break the feed, with the clock well past the fetch.
    class _LaterDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 20)

    monkeypatch.setattr(news_module, "date", _LaterDate)
    monkeypatch.setattr(news_module, "ttl_for", lambda _key: 0)

    def explode(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    degraded = news_module.get_news("NVDA", days=7)

    assert degraded.fetched_at == "2026-07-01", "stale headlines must report their real vintage"
    assert any("stale" in warning for warning in degraded.warnings)


def test_a_recent_failure_short_circuits_instead_of_piling_up(monkeypatch) -> None:
    """N callers behind a failed fetch must not each pay a full timeout.

    Nothing is cached on failure, so every waiter's re-read misses; without a
    failure memo each one runs its own upstream attempt inside the lock.
    """

    attempts: list[str] = []

    def explode(*args, **kwargs):
        attempts.append("try")
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    first = news_module.get_news("NVDA", days=7)
    second = news_module.get_news("NVDA", days=7)

    assert first.items == [] and second.items == []
    assert len(attempts) == 1, "the second call must be served from the failure memo"
    assert any("fetch failed" in warning for warning in second.warnings)


def test_eviction_never_drops_a_referenced_but_unheld_lock(monkeypatch) -> None:
    """The race is "referenced but not yet acquired", which `locked()` cannot see.

    A caller takes the lock object under the mutex and acquires it as a separate
    step. An eviction sweep landing in that window sees `locked() is False`,
    deletes the key, and a later caller mints a second lock for the same key —
    two threads then run the critical section together and single-flight breaks.
    Reference counting closes the window; this reproduces it directly.
    """

    import threading

    monkeypatch.setattr(news_module, "_MAX_FETCH_LOCKS", 2)

    # Exactly the window: a reference is registered, the lock is NOT acquired.
    original = threading.Lock()
    with news_module._fetch_locks_mutex:
        news_module._fetch_locks["in-flight"] = original
        news_module._lock_refs["in-flight"] = 1

    # Drive enough traffic to trigger repeated sweeps.
    for index in range(6):
        with news_module._fetch_lock(f"other-{index}"):
            pass

    assert "in-flight" in news_module._fetch_locks, "a referenced key must survive eviction"
    assert news_module._fetch_locks["in-flight"] is original, (
        "the key must still map to the SAME lock object, or a second caller would "
        "acquire a different one and both would fetch"
    )


def test_unreferenced_locks_are_reclaimed(monkeypatch) -> None:
    monkeypatch.setattr(news_module, "_MAX_FETCH_LOCKS", 4)

    for index in range(20):
        with news_module._fetch_lock(f"key-{index}"):
            pass

    assert len(news_module._fetch_locks) <= news_module._MAX_FETCH_LOCKS, (
        "unreferenced locks must be reclaimed; asserting against the number inserted "
        "instead of the cap is trivially true and tests nothing"
    )
    assert news_module._lock_refs == {}, "no reference should outlive its holder"


def test_memo_warning_says_it_was_not_retried(monkeypatch) -> None:
    attempts: list[str] = []

    def explode(*args, **kwargs):
        attempts.append("try")
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    news_module.get_news("NVDA", days=7)
    second = news_module.get_news("NVDA", days=7)

    assert len(attempts) == 1
    joined = " ".join(second.warnings)
    assert "not retried" in joined, "a remembered failure must not read as a fresh attempt"
    assert "remembered for" in joined


def test_memo_expires(monkeypatch) -> None:
    attempts: list[str] = []

    def explode(*args, **kwargs):
        attempts.append("try")
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)
    news_module.get_news("NVDA", days=7)

    # Age the memo past its window rather than patching the clock globally.
    with news_module._fetch_locks_mutex:
        deadline, message = news_module._recent_failures[news_module._cache_key("NVDA", 7, None)]
        news_module._recent_failures[news_module._cache_key("NVDA", 7, None)] = (deadline - 999, message)

    news_module.get_news("NVDA", days=7)

    assert len(attempts) == 2, "an expired memo must allow a real retry"


def test_memo_is_scoped_per_cache_key(monkeypatch) -> None:
    """A failure on days=7 must not suppress days=30."""

    attempts: list[int] = []

    def explode(*args, **kwargs):
        attempts.append(1)
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(news_module.urllib.request, "urlopen", explode)

    news_module.get_news("NVDA", days=7)
    news_module.get_news("NVDA", days=30)

    assert len(attempts) == 2, "different windows are different keys"
