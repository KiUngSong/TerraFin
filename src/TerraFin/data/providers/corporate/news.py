"""Headline retrieval from Google News RSS.

This is the single home for news fetching. The weekly-report builder previously
carried its own uncached copy that kept only the title and date, discarding the
link and publisher, so a headline's provenance could not be recovered.

Only headline metadata is requested and stored — never article bodies.
"""

import hashlib
import logging
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts.news import NewsFeed, NewsItem


log = logging.getLogger(__name__)

_RSS_ENDPOINT = "https://news.google.com/rss/search"
_NS = "news.google"
_TIMEOUT_SECONDS = 10

# One query for a week routinely returns ~100 items; keep a hard ceiling so a
# caller cannot pull an unbounded feed into context.
MAX_ITEMS = 100
DEFAULT_DAYS = 7

# Google truncates very long queries anyway, and an unbounded string is a
# denial-of-service shaped input for a cached, per-query resource.
MAX_QUERY_CHARS = 200

# Per-key single-flight. `CacheManager.get_payload` serialises concurrent misses
# for a registered source; the static file-cache path does not, so N concurrent
# identical queries would otherwise fire N upstream fetches. Mirrors
# `CacheManager._get_fetch_lock`.
_fetch_locks: dict[str, threading.Lock] = {}
_fetch_locks_mutex = threading.Lock()

# One lock per distinct query would otherwise grow without bound — the same
# unbounded-key-space problem this module avoids for cache sources. Eviction is
# reference-counted rather than keyed off `Lock.locked()`: a caller receives the
# lock object BEFORE acquiring it, so a sweep in that window would delete a key
# whose lock is about to be held, letting a later caller mint a second lock for
# the same key and run the critical section concurrently.
_MAX_FETCH_LOCKS = 256
_lock_refs: dict[str, int] = {}

# A failed fetch is not cached, so without this every waiter behind the lock
# would run its own full-timeout attempt: N callers cost N x timeout. Remember a
# failure briefly so waiters fail fast instead of queueing.
_FAILURE_MEMO_SECONDS = 60
_MAX_FAILURE_MEMOS = 256
_recent_failures: dict[str, tuple[float, str]] = {}


@contextmanager
def _fetch_lock(key: str):
    """Hold the single-flight lock for `key`, reference-counted for eviction."""
    with _fetch_locks_mutex:
        lock = _fetch_locks.get(key)
        if lock is None:
            if len(_fetch_locks) >= _MAX_FETCH_LOCKS:
                # Only unreferenced keys are dropped; a key someone is about to
                # acquire always has a live reference by this point. A refcount
                # is popped when it reaches zero, so "absent from _lock_refs" is
                # exactly "unreferenced". The cap is therefore soft: if every
                # key is live the dict stays above it, which is correct — a held
                # lock must never be evicted.
                for stale_key in [k for k in list(_fetch_locks) if k not in _lock_refs]:
                    _fetch_locks.pop(stale_key, None)
            lock = threading.Lock()
            _fetch_locks[key] = lock
        _lock_refs[key] = _lock_refs.get(key, 0) + 1

    try:
        with lock:
            yield
    finally:
        with _fetch_locks_mutex:
            remaining = _lock_refs.get(key, 1) - 1
            if remaining <= 0:
                _lock_refs.pop(key, None)
            else:
                _lock_refs[key] = remaining


def _recent_failure(key: str) -> str | None:
    """A remembered failure for this key, phrased so it cannot read as a fresh one."""
    with _fetch_locks_mutex:
        entry = _recent_failures.get(key)
        if entry is None:
            return None
        deadline, message = entry
        now = time.monotonic()
        if now >= deadline:
            del _recent_failures[key]
            return None
        age = int(_FAILURE_MEMO_SECONDS - (deadline - now))
    return (
        f"not retried: a fetch failed {age}s ago and failures are remembered for "
        f"{_FAILURE_MEMO_SECONDS}s ({message})"
    )


def _remember_failure(key: str, message: str) -> None:
    with _fetch_locks_mutex:
        if len(_recent_failures) >= _MAX_FAILURE_MEMOS:
            # Drop only entries that have already expired; clearing wholesale
            # would discard fresh memos and re-open the pile-up.
            now = time.monotonic()
            for stale_key in [k for k, (deadline, _) in _recent_failures.items() if now >= deadline]:
                del _recent_failures[stale_key]
            if len(_recent_failures) >= _MAX_FAILURE_MEMOS:
                _recent_failures.clear()
        _recent_failures[key] = (time.monotonic() + _FAILURE_MEMO_SECONDS, message)


class NewsUnavailableError(RuntimeError):
    """Raised when the feed could not be fetched or parsed.

    Propagating instead of returning an empty feed keeps a transient failure out
    of the cache: an empty result written to disk would pin "no news" for a full
    TTL and make a re-run reproduce the blank.
    """


def _cache_key(query: str, days: int, as_of: str | None) -> str:
    """Stable, collision-free, filesystem-safe cache key.

    The query is hashed rather than slugified: slugifying collided (`"AAPL
    earnings"` and `"AAPL_earnings"` mapped to one key) and an unbounded query
    produced a filename over the 255-byte limit, surfacing as an OSError that
    leaked the cache path.
    """
    digest = hashlib.sha256(query.lower().strip().encode("utf-8")).hexdigest()[:16]
    suffix = f"__{as_of}" if as_of else ""
    return f"{digest}__{days}d{suffix}"


def _build_url(query: str, *, days: int, as_of: date) -> str:
    after = (as_of - timedelta(days=days)).isoformat()
    before = (as_of + timedelta(days=1)).isoformat()
    params = urllib.parse.urlencode(
        {
            "q": f'"{query}" stock after:{after} before:{before}',
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    return f"{_RSS_ENDPOINT}?{params}"


def _fetch_raw(query: str, days: int, as_of: str | None = None) -> dict:
    """Fetch and parse the feed into JSON-safe records.

    Returns primitives only: the cache persists dict payloads as JSON, so
    anything richer would be silently stringified.
    """
    anchor = date.fromisoformat(as_of) if as_of else date.today()
    url = _build_url(query, days=days, as_of=anchor)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    records: list[dict] = []
    warnings: list[str] = []
    fetched_at = date.today().isoformat()
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read()
    except Exception as exc:  # noqa: BLE001 - urllib raises many shapes
        log.debug("news: fetch failed for %r: %s", query, exc)
        raise NewsUnavailableError(f"news fetch failed: {type(exc).__name__}") from exc

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log.debug("news: parse failed for %r: %s", query, exc)
        raise NewsUnavailableError(f"news feed unparseable: {exc}") from exc

    skipped = 0
    for item in root.findall(".//item")[:MAX_ITEMS]:
        title = (item.findtext("title") or "").strip()
        raw_date = item.findtext("pubDate")
        if not title or not raw_date:
            skipped += 1
            continue
        try:
            published = parsedate_to_datetime(raw_date).date().isoformat()
        except (TypeError, ValueError):
            skipped += 1
            continue
        source_el = item.find("source")
        records.append(
            {
                "title": title,
                "publishedAt": published,
                # A news.google.com redirect, not the publisher's canonical URL.
                "url": (item.findtext("link") or "").strip() or None,
                "source": (source_el.text or "").strip() if source_el is not None else None,
                "sourceUrl": source_el.get("url") if source_el is not None else None,
            }
        )
    if skipped:
        warnings.append(f"{skipped} feed item(s) skipped for a missing title or unparseable date")
    return {
        "records": records,
        "warnings": warnings,
        "query": query,
        "days": days,
        "fetchedAt": fetched_at,
    }


def get_news(
    query: str,
    *,
    days: int = DEFAULT_DAYS,
    limit: int = 25,
    as_of: str | None = None,
) -> NewsFeed:
    """Headlines matching `query` over the trailing `days`, newest first.

    Returns an empty feed with a warning rather than raising when the upstream
    feed is unreachable — a missing catalyst is information, not an error.

    `as_of` (YYYY-MM-DD) anchors the window in the past instead of today, which
    the weekly-report builder needs when regenerating an earlier week.

    A failed fetch is remembered for `_FAILURE_MEMO_SECONDS`, so a caller inside
    that window is served stale headlines (or an empty feed) without a retry.
    The warning says so explicitly rather than implying a fresh attempt.
    """
    normalized = query.strip()
    if not normalized:
        raise ValueError("Query is required")
    if len(normalized) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters, got {len(normalized)}")
    if days < 1 or days > 90:
        raise ValueError(f"days must be between 1 and 90, got {days}")
    if limit < 1 or limit > MAX_ITEMS:
        raise ValueError(f"limit must be between 1 and {MAX_ITEMS}, got {limit}")

    from TerraFin.data.cache.manager import CacheManager

    # Static file cache rather than a registered payload spec: every distinct
    # query would otherwise become a permanent background-refresh source and a
    # permanent state-file entry, and a free-form query space is unbounded.
    key = _cache_key(normalized, days, as_of)
    ttl = ttl_for("news.google")
    payload = CacheManager.file_cache_read(_NS, key, ttl)
    warnings: list[str] = []
    if payload is None:
        recent = _recent_failure(key)
        if recent is not None:
            stale = CacheManager.file_cache_read_stale(_NS, key)
            if stale is None:
                return NewsFeed(query=normalized, days=days, items=[], warnings=[recent])
            payload = stale
            warnings.append(f"feed unavailable, serving stale headlines: {recent}")
        else:
            with _fetch_lock(key):
                # Re-read inside the lock: a concurrent caller may have just
                # populated this key while this one waited.
                payload = CacheManager.file_cache_read(_NS, key, ttl)
                if payload is None:
                    recent = _recent_failure(key)
                    if recent is not None:
                        raise_message = recent
                    else:
                        raise_message = None
                        try:
                            payload = _fetch_raw(normalized, days, as_of)
                        except NewsUnavailableError as exc:
                            raise_message = str(exc)
                            _remember_failure(key, raise_message)
                        else:
                            CacheManager.file_cache_write(_NS, key, payload)
                    if raise_message is not None:
                        stale = CacheManager.file_cache_read_stale(_NS, key)
                        if stale is None:
                            return NewsFeed(
                                query=normalized, days=days, items=[], warnings=[raise_message]
                            )
                        payload = stale
                        warnings.append(
                            f"feed unavailable, serving stale headlines: {raise_message}"
                        )
    warnings.extend(payload.get("warnings") or [])

    items: list[NewsItem] = []
    for record in payload.get("records") or []:
        try:
            items.append(
                NewsItem(
                    title=str(record.get("title") or ""),
                    published_at=str(record.get("publishedAt") or ""),
                    url=record.get("url"),
                    source=record.get("source"),
                    source_url=record.get("sourceUrl"),
                    query=normalized,
                )
            )
        except ValueError:
            continue

    items.sort(key=lambda item: item.published_at, reverse=True)
    total = len(items)
    if total > limit:
        warnings.append(f"{total} headlines matched; returning the {limit} most recent")
        items = items[:limit]
    return NewsFeed(
        query=normalized,
        days=days,
        items=items,
        warnings=warnings,
        fetched_at=str(payload.get("fetchedAt") or "") or None,
    )


def clear_news_cache() -> None:
    """Drop every cached headline feed. Registered in `data/cache/registry.py`."""
    from TerraFin.data.cache.manager import CacheManager

    CacheManager.file_cache_remove_tree(_NS)
