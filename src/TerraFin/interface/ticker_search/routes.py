"""Ticker search API.

Endpoint: GET /api/ticker-search?q=<query>

Returns indicators (local registry) and stocks (Yahoo Finance proxy).
Korean queries are translated via static alias map before hitting Yahoo.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Query

from .aliases_kr import lookup_kr_alias, prefix_match_kr_aliases
from .kr_listings import load_kr_listings


log = logging.getLogger(__name__)

_KOREAN_RE = re.compile(r"[가-힣]")

# Yahoo "exchange" codes for primary equity listings we surface.
# US + Korea + Japan covers TerraFin's primary user base; other
# regional cross-listings (.DE, .L, .SW, .HK, etc.) are filtered out
# to avoid duplicate results for the same underlying company.
_PRIMARY_EXCHANGES: set[str] = {
    # US
    "NMS", "NGM", "NCM", "NYQ", "ASE", "BATS", "ARCA", "PCX",
    "PNK", "OQB", "OQX",
    # Korea
    "KSC",  # KOSPI
    "KOE",  # KOSDAQ
    # Japan
    "JPX",  # Tokyo Stock Exchange
}


def _is_korean(q: str) -> bool:
    return bool(_KOREAN_RE.search(q))


def _build_indicator_entries() -> list[dict[str, Any]]:
    """The canonical user-facing indicator catalog.

    PRIVATE_SERIES is the data-source layer (cache namespaces + fetcher
    bindings) — it is NOT a UI surface. Market and Economic registries
    wrap it where appropriate (e.g. ``MARKET_INDICATOR_REGISTRY["CAPE"]``
    fetches via the private cape series). The wrappers are the canonical
    chart-UI entry points; the underlying source layer is not surfaced.
    """
    from TerraFin.data.providers.economic import indicator_registry
    from TerraFin.data.providers.market import MARKET_INDICATOR_REGISTRY

    out: list[dict[str, Any]] = []
    for name, ind in MARKET_INDICATOR_REGISTRY.items():
        out.append({"symbol": name, "name": ind.description or name, "group": "Market"})
    for name, ind in indicator_registry._indicators.items():
        out.append({"symbol": name, "name": ind.description or name, "group": "Economic"})
    return out


def _search_indicators(q: str) -> list[dict[str, Any]]:
    """Substring match across the indicator catalog."""
    q_lower = q.strip().lower()
    if not q_lower:
        return []
    matches = [
        entry for entry in _build_indicator_entries()
        if q_lower in f"{entry['symbol']} {entry['name']}".lower()
    ]
    return matches[:10]


def _search_naver_kr(q: str) -> list[dict[str, Any]]:
    """Hit Naver autocomplete for KR equity matches.

    Naver returns structured rows for KR-listed stocks when query closely
    matches a Korean company name. Maps KOSPI→.KS, KOSDAQ→.KQ to keep
    symbols Yahoo-compatible for downstream chart loading.
    """
    try:
        import requests
    except ImportError:
        return []

    try:
        resp = requests.get(
            "https://ac.search.naver.com/nx/ac",
            params={
                "q": q,
                "q_enc": "UTF-8",
                "st": 100,
                "frm": "stock",
                "r_format": "json",
                "r_enc": "UTF-8",
                "t_koreng": 1,
                "ans": 2,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=4,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.debug("Naver search failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for ans in data.get("answer", []):
        # Row shape: ["20","<name> 주가","ansstk","","","<code>","<market>", ...]
        if not isinstance(ans, list) or len(ans) < 7:
            continue
        code = str(ans[5] or "").strip()
        market = str(ans[6] or "").strip().upper()
        title = str(ans[1] or "").strip()
        # Strip trailing " 주가" the autocomplete adds
        name = re.sub(r"\s*주가$", "", title) or code
        if not code or not market:
            continue
        if market == "KOSPI":
            symbol = f"{code}.KS"
            exchange = "KSC"
        elif market == "KOSDAQ":
            symbol = f"{code}.KQ"
            exchange = "KOE"
        else:
            continue
        out.append({"symbol": symbol, "name": name, "exchange": exchange, "type": "EQUITY"})
    return out


def _search_yahoo(q: str) -> list[dict[str, Any]]:
    """Hit Yahoo Finance public search; return up to 8 stock matches."""
    try:
        import requests
    except ImportError:
        return []

    try:
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 8, "newsCount": 0, "lang": "en-US"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=4,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.debug("Yahoo search failed: %s", exc)
        return []

    quotes = data.get("quotes", [])
    out: list[dict[str, Any]] = []
    for q_item in quotes:
        sym = q_item.get("symbol")
        if not sym:
            continue
        exch = q_item.get("exchange") or ""
        qtype = q_item.get("quoteType") or ""
        # Drop derivatives / future / options noise
        if qtype in {"OPTION", "FUTURE", "MUTUALFUND"}:
            continue
        if qtype in {"EQUITY", "ETF"} and exch not in _PRIMARY_EXCHANGES:
            continue
        out.append(
            {
                "symbol": sym,
                "name": q_item.get("shortname") or q_item.get("longname") or sym,
                "exchange": exch,
                "type": qtype,
            }
        )
    return out


def create_ticker_search_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/ticker-search/registry")
    def ticker_search_registry() -> dict[str, Any]:
        """Static client-cacheable data: KR aliases + indicator names.

        Frontend fetches once at app load, then does local prefix matching
        without round-tripping to the server for every keystroke.
        """
        from .aliases_kr import KR_ALIASES

        indicators = _build_indicator_entries()

        # Curated US/intl aliases first (so a hand-picked entry like
        # 애플 → AAPL wins over an accidental KRX collision); then the
        # full KRX listing for KOSPI + KOSDAQ companies.
        kr_aliases = dict(load_kr_listings())
        kr_aliases.update(KR_ALIASES)

        return {
            "kr_aliases": kr_aliases,
            "indicators": indicators,
        }

    @router.get("/api/ticker-search")
    def ticker_search(q: str = Query(..., min_length=1, max_length=64)) -> dict[str, Any]:
        query = q.strip()
        if not query:
            return {"indicators": [], "stocks": [], "translated": None}

        indicators = _search_indicators(query)

        translated: str | None = None
        if _is_korean(query):
            exact = lookup_kr_alias(query)
            if exact is not None:
                translated = exact
                # Exact match → enrich with Yahoo metadata for the resolved ticker
                stocks = _search_yahoo(exact)
            else:
                # Prefix match against the static alias map for live suggestions
                matches = prefix_match_kr_aliases(query)
                stocks = [
                    {"symbol": ticker, "name": display, "exchange": "", "type": "EQUITY"}
                    for display, ticker in matches
                ]
                # Also try Naver for Korean-listed stocks the static map doesn't cover
                if not stocks:
                    stocks = _search_naver_kr(query)
            return {"indicators": indicators, "stocks": stocks, "translated": translated}

        stocks = _search_yahoo(query)
        return {"indicators": indicators, "stocks": stocks, "translated": None}

    return router
