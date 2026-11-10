"""Web search and article text, for research that needs sources TerraFin holds no
feed for -- a private company's reported revenue, a market reaction, an analyst's
read of the news.

Search goes first through Exa's hosted MCP endpoint, which needs no API key and
returns each result with text from the page itself. When Exa fails, search falls
back to DuckDuckGo's HTML endpoint, which returns publisher URLs directly.
DuckDuckGo answers a burst of queries with a bot check, so a blocked search
falls back again, to Bing News RSS, whose links carry the publisher URL in a
`url=` parameter. Google News RSS (`corporate/news.py`)
is not used: its links are `news.google.com` redirects that do not resolve to
the article without a browser.

Unlike `corporate/news.py`, this module does read article bodies. Nothing here
caches or stores them; a caller keeps only the sentences it cites.
"""

import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup


log = logging.getLogger(__name__)

_EXA_ENDPOINT = "https://mcp.exa.ai/mcp"
# A result's page text past this is cut: the model reads the page itself for more.
_MAX_SNIPPET_CHARS = 2000
_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_BING_NEWS_ENDPOINT = "https://www.bing.com/news/search"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_TIMEOUT_SECONDS = 10
# A page past this is not an article; stop reading rather than parse it.
_MAX_PAGE_BYTES = 3_000_000
MAX_RESULTS = 25

# DuckDuckGo's `df` filter. None searches every date.
_RECENCY = {"day": "d", "week": "w", "month": "m", "year": "y"}
# Bing News's `interval` filter. It has no year window, so "year" searches every date.
_BING_RECENCY = {"day": "4", "week": "7", "month": "8"}

# A paragraph shorter than this is a caption, a byline or a button label.
_MIN_PARAGRAPH_CHARS = 40

# Page URLs come from search results, so a fetch may only reach a public host on
# a standard web port, and every redirect hop is held to the same test.
_ALLOWED_PORTS = frozenset({80, 443})
_MAX_REDIRECTS = 3


class WebSearchError(RuntimeError):
    """Raised when the search endpoint could not be reached or parsed."""


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class WebArticle:
    url: str
    title: str
    paragraphs: tuple[str, ...]


class UnsafeURLError(ValueError):
    """Raised for a URL whose host is not public or whose port is not 80 or 443."""


Resolver = Callable[[str, int], list[str]]


def _resolve_addresses(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _check_url(url: str, resolve: Resolver) -> None:
    """Raise `UnsafeURLError` unless every address `url`'s host resolves to is public.

    The check and the connection resolve separately, so a host that answers
    differently the second time (DNS rebinding) is not caught here.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURLError(f"refusing {url!r}: only http(s) URLs with a host are fetched")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise UnsafeURLError(f"refusing {url!r}: port {port} is not 80 or 443")
    for address in resolve(parsed.hostname, port):
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise UnsafeURLError(f"refusing {url!r}: {parsed.hostname} resolves to non-public address {ip}")


class _CheckedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTS

    def __init__(self, resolve: Resolver) -> None:
        self._resolve = resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl, self._resolve)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, *, data: bytes | None = None, resolve: Resolver = _resolve_addresses) -> bytes:
    _check_url(url, resolve)
    opener = urllib.request.build_opener(_CheckedRedirectHandler(resolve))
    request = urllib.request.Request(url, data=data, headers={"User-Agent": _USER_AGENT})
    with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read(_MAX_PAGE_BYTES)


def _result_url(href: str) -> str | None:
    """The publisher URL inside a DuckDuckGo `/l/?uddg=` redirect."""
    parsed = urllib.parse.urlparse(href if "://" in href else f"https:{href}")
    target = urllib.parse.parse_qs(parsed.query).get("uddg")
    url = target[0] if target else href
    # Sponsored results route through the ad click endpoint, not a publisher.
    if not url.startswith("http") or "duckduckgo.com/y.js" in url:
        return None
    return url


def search_web(query: str, *, limit: int = 8, recency: str | None = None) -> list[WebResult]:
    """Search results for `query`, best first.

    `recency` is one of "day", "week", "month", "year", or None for any date.
    Exa takes no date filter, so it is asked to rank recent pages first.
    Falls back to DuckDuckGo when Exa fails, and to Bing News when DuckDuckGo
    blocks or fails too; raises `WebSearchError` only when all three do.
    """
    normalized = query.strip()
    if not normalized:
        raise ValueError("Query is required")
    if limit < 1 or limit > MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}, got {limit}")
    if recency is not None and recency not in _RECENCY:
        raise ValueError(f"recency must be one of {sorted(_RECENCY)} or None, got {recency!r}")
    try:
        results = _search_exa(normalized, limit=limit, recency=recency)
        if results:
            return results
        raise WebSearchError("Exa returned no results")
    except WebSearchError as exa:
        log.warning("web: %s; falling back to DuckDuckGo", exa)
    try:
        results = _search_duckduckgo(normalized, limit=limit, recency=recency)
        if not results:
            # A results page with no hits is indistinguishable from a soft block.
            raise WebSearchError("DuckDuckGo returned no results")
        return results
    except WebSearchError as primary:
        log.info("web: %s; falling back to Bing News", primary)
        try:
            return _search_bing_news(normalized, limit=limit, recency=recency)
        except WebSearchError as fallback:
            raise WebSearchError(f"{primary}; Bing News fallback: {fallback}") from fallback


def _search_exa(query: str, *, limit: int, recency: str | None) -> list[WebResult]:
    arguments: dict[str, object] = {"query": query, "numResults": limit}
    if recency is not None:
        arguments["objective"] = f"Rank first the pages published in the past {recency}."
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "web_search_exa", "arguments": arguments}}
    request = urllib.request.Request(
        _EXA_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "TerraFin",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_PAGE_BYTES).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - urllib raises many shapes
        status = f" {exc.code}" if isinstance(exc, urllib.error.HTTPError) else ""
        raise WebSearchError(f"Exa search failed: {type(exc).__name__}{status}") from exc
    # The reply is one JSON-RPC message, sent bare or as a server-sent event.
    message = None
    for line in [body, *body.splitlines()]:
        line = line.strip().removeprefix("data:").strip()
        if line.startswith("{"):
            try:
                message = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    result = message.get("result") if isinstance(message, dict) else None
    parts = result.get("content") if isinstance(result, dict) else None
    texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)] if isinstance(parts, list) else []
    if not isinstance(result, dict) or result.get("isError"):
        detail = " ".join(texts)[:200]
        raise WebSearchError("Exa search returned an error" + (f": {detail}" if detail else ""))
    text = "\n\n---\n\n".join(texts)
    results: list[WebResult] = []
    seen: set[str] = set()
    for block in text.split("\n\n---\n\n"):
        fields: dict[str, str] = {}
        lines = block.splitlines()
        for at, line in enumerate(lines):
            key, sep, value = line.partition(":")
            if not sep or key not in ("Title", "URL", "Published", "Highlights", "Text"):
                continue
            if key in ("Highlights", "Text"):
                # The page text runs to the end of the block.
                fields["text"] = "\n".join([value.strip(), *lines[at + 1 :]]).strip()
                break
            fields[key] = value.strip()
        url = fields.get("URL", "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        published = fields.get("Published", "")
        snippet = fields.get("text", "")[:_MAX_SNIPPET_CHARS]
        if published and published != "N/A":
            snippet = f"Published {published[:10]}. {snippet}"
        title = fields.get("Title", "")
        results.append(WebResult(title="" if title == "N/A" else title, url=url, snippet=snippet))
        if len(results) >= limit:
            break
    return results


def _search_bing_news(query: str, *, limit: int, recency: str | None) -> list[WebResult]:
    params = {"q": query, "format": "rss"}
    if recency in _BING_RECENCY:
        params["qft"] = f'interval="{_BING_RECENCY[recency]}"'
    try:
        body = _get(f"{_BING_NEWS_ENDPOINT}?{urllib.parse.urlencode(params)}")
        root = ET.fromstring(body)
    except Exception as exc:  # noqa: BLE001 - urllib and the XML parser raise many shapes
        raise WebSearchError(f"Bing News search failed: {type(exc).__name__}") from exc
    results: list[WebResult] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        link = item.findtext("link") or ""
        target = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url")
        url = target[0] if target else link
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        results.append(
            WebResult(
                title=(item.findtext("title") or "").strip(),
                url=url,
                snippet=(item.findtext("description") or "").strip(),
            )
        )
        if len(results) >= limit:
            break
    return results


def _search_duckduckgo(normalized: str, *, limit: int, recency: str | None) -> list[WebResult]:
    params = {"q": normalized}
    if recency is not None:
        params["df"] = _RECENCY[recency]
    try:
        body = _get(_SEARCH_ENDPOINT, data=urllib.parse.urlencode(params).encode())
    except Exception as exc:  # noqa: BLE001 - urllib raises many shapes
        raise WebSearchError(f"web search failed: {type(exc).__name__}") from exc

    soup = BeautifulSoup(body, "html.parser")
    results: list[WebResult] = []
    seen: set[str] = set()
    for anchor in soup.select("a.result__a"):
        url = _result_url(anchor.get("href") or "")
        if url is None or url in seen:
            continue
        seen.add(url)
        container = anchor.find_parent(class_="result")
        snippet_el = container.select_one(".result__snippet") if container is not None else None
        results.append(
            WebResult(
                title=anchor.get_text(" ", strip=True),
                url=url,
                snippet=snippet_el.get_text(" ", strip=True) if snippet_el is not None else "",
            )
        )
        if len(results) >= limit:
            break
    if not results and "result__a" not in body.decode("utf-8", "ignore"):
        # An empty page without the results markup is a block page, not "no hits".
        raise WebSearchError("web search returned no results page")
    return results


def fetch_article(url: str) -> WebArticle | None:
    """The readable paragraphs of the page at `url`, or None when unreadable.

    A paywalled or script-rendered page yields no paragraphs and comes back as
    None, the same as a failed fetch: either way there is nothing to cite.
    """
    try:
        body = _get(url)
    except Exception as exc:  # noqa: BLE001 - one bad page is not a failed search
        log.debug("web: fetch failed for %s: %s", url, exc)
        return None
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.body or soup
    paragraphs: list[str] = []
    seen: set[str] = set()
    for element in root.find_all("p"):
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) < _MIN_PARAGRAPH_CHARS or text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)
    if not paragraphs:
        return None
    title = soup.title.get_text(" ", strip=True) if soup.title is not None else ""
    return WebArticle(url=url, title=title, paragraphs=tuple(paragraphs))


def fetch_articles(urls: list[str], *, workers: int = 6) -> list[WebArticle]:
    """Fetch several pages at once, keeping the readable ones in input order."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as pool:
        articles = list(pool.map(fetch_article, urls))
    return [article for article in articles if article is not None]
