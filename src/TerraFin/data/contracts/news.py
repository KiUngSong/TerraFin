"""Headline contract.

Headlines only — title, timestamp, publisher, and a link. No article bodies are
fetched or stored, which keeps this on the right side of publisher terms while
still answering "why now" for a ticker.

`url` is deliberately typed as a redirect rather than a canonical article URL:
Google News RSS returns its own `news.google.com/rss/articles/...` link, which
resolves in a browser but is not the publisher's address. Callers that need the
canonical URL must follow the redirect themselves.
"""

import re
from dataclasses import dataclass


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class NewsItem:
    """One headline."""

    title: str
    published_at: str
    url: str | None = None
    source: str | None = None
    source_url: str | None = None
    query: str | None = None

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("NewsItem.title is required")
        if not _DATE_RE.match(self.published_at):
            raise ValueError(f"NewsItem.published_at must be YYYY-MM-DD, got {self.published_at!r}")

    @property
    def headline(self) -> str:
        """Title with the trailing " - Publisher" suffix removed when present.

        Matched exactly against the known publisher rather than by pattern: a
        regex for "dash then short tail" also eats real content, turning
        "Stock jumps 5% - here's why" into "Stock jumps 5%".
        """
        if not self.source:
            return self.title
        suffix = f" - {self.source}"
        if self.title.endswith(suffix):
            return self.title[: -len(suffix)] or self.title
        return self.title


@dataclass
class NewsFeed:
    """Headlines for one query window, newest first."""

    query: str
    days: int
    items: list[NewsItem]
    warnings: list[str]
    # Date the feed was fetched, carried through the cache so a stale-served
    # feed reports its true vintage rather than today. Mirrors
    # `ConsensusEstimates.as_of`.
    fetched_at: str | None = None

    @classmethod
    def make_empty(cls, query: str = "", days: int = 0) -> "NewsFeed":
        return cls(query=query, days=days, items=[], warnings=[])

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
