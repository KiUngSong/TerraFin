"""NexTick Daily's latest English issue, read from the archive's public manifest."""

import json
import threading
import time
import urllib.request


SITE = "https://nextickdaily.com"
_MANIFEST_URL = f"{SITE}/manifest.json"
_TIMEOUT_SECONDS = 10
# The site serves the manifest with a 5-minute cache, so a fresher read gains nothing.
_TTL_SECONDS = 300

_lock = threading.Lock()
_cached: tuple[float, dict | None] = (float("-inf"), None)


def latest_english_issue() -> dict | None:
    """The newest issue with an English edition: the US trading day it covers, its headline, its URL and when
    it was published. None when no issue has an English edition."""
    global _cached
    with _lock:
        fetched_at, issue = _cached
    if time.monotonic() - fetched_at < _TTL_SECONDS:
        return issue
    request = urllib.request.Request(_MANIFEST_URL, headers={"User-Agent": "TerraFin"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            entries = json.load(response)
    except Exception:
        # A failed read serves the last issue read, since an issue stands for a whole day.
        if issue is not None:
            with _lock:
                _cached = (time.monotonic(), issue)
            return issue
        raise
    english = [entry for entry in entries if entry.get("hook_en") and entry.get("et_date")]
    newest = max(english, key=lambda entry: entry["et_date"], default=None)
    issue = None
    if newest is not None:
        issue = {
            "date": newest["et_date"],
            "headline": newest["hook_en"],
            "url": f"{SITE}/en/{newest['et_date']}/",
            "publishedAt": newest.get("published_at"),
        }
    with _lock:
        _cached = (time.monotonic(), issue)
    return issue
