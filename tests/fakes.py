"""Shared stub doubles for the TerraFin test suite.

Imported as `from fakes import ...`; `tests/` is on `sys.path` via the
`pythonpath` setting in `pyproject.toml`.

`BaseFakeService` is the single stub service used by every test that builds the
default capability registry. `build_default_capability_registry` binds
`service.<method>` eagerly for each registered capability, so a fake that is
missing a method fails at registry-build time with `AttributeError`.

To keep that from turning every new capability into a mechanical edit across
several test modules, unknown attributes resolve through `__getattr__` to a
generic stub. Methods are still spelled out explicitly below when a test
asserts on their payload shape; anything added later works without changes
here. Override a single method in a subclass when a module needs a different
payload.
"""

from typing import Any


def processing() -> dict[str, object]:
    """Return the standard `processing` metadata block used by stub payloads."""

    return {
        "requestedDepth": "auto",
        "resolvedDepth": "full",
        "loadedStart": "2024-01-01",
        "loadedEnd": "2024-12-31",
        "isComplete": True,
        "hasOlder": False,
        "sourceVersion": "test-source",
        "view": "daily",
    }


class BaseFakeService:
    """Stub `TerraFinAgentService` covering the default capability registry."""

    def __getattr__(self, name: str) -> Any:
        """Resolve capabilities with no explicit stub to a generic payload.

        Private and dunder lookups must still raise so that `copy`, `pickle`,
        and pytest introspection keep working.
        """

        if name.startswith("_"):
            raise AttributeError(name)

        def _auto_stub(*args: Any, **kwargs: Any) -> dict[str, object]:
            return {
                "capability": name,
                "args": list(args),
                "kwargs": kwargs,
                "processing": processing(),
            }

        return _auto_stub

    def resolve(self, query: str) -> dict[str, object]:
        return {"type": "stock", "name": query.upper(), "path": f"/stock/{query.upper()}", "processing": processing()}

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"ticker": name, "seriesType": "candlestick", "count": 1, "data": [], "processing": {**processing(), "requestedDepth": depth, "view": view}}

    def patterns(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"ticker": name, "signals": [], "total": 0, "processing": {**processing(), "requestedDepth": depth, "view": view}}

    def fcf_history(self, ticker: str, years: int = 10) -> dict[str, object]:
        return {
            "ticker": ticker, "years": years, "rows": [],
            "candidates": {"threeYearAvg": None, "latestAnnual": None, "ttm": None},
            "autoSelectedSource": "annual", "processing": processing(),
        }

    def similarity_search(self, ticker: str, universe: str = "sp500+nasdaq100+kospi200", period: str = "1y", top_n: int = 20) -> dict[str, object]:
        return {"ticker": ticker, "period": period, "pool": {}, "results": [], "count": 0, "processing": processing()}

    def indicators(
        self,
        name: str,
        indicators: str,
        *,
        depth: str = "auto",
        view: str = "daily",
    ) -> dict[str, object]:
        return {
            "ticker": name,
            "indicators": {"rsi": {"name": "rsi", "offset": 0, "values": {"value": 55.0}}},
            "unknown": [],
            "processing": {**processing(), "requestedDepth": depth, "view": view, "indicatorQuery": indicators},
        }

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "ticker": name,
            "price_action": {"current": 100.0},
            "indicators": {"rsi": 55.0},
            "market_breadth": [],
            "watchlist": [],
            "processing": {**processing(), "requestedDepth": depth, "view": view},
        }

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"name": name, "confidence": 0.2, "processing": {**processing(), "requestedDepth": depth, "view": view}}

    def company_info(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "shortName": f"{ticker} Corp", "processing": processing()}

    def earnings(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "earnings": [], "processing": processing()}

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, object]:
        return {"ticker": ticker, "statement": statement, "period": period, "columns": [], "rows": [], "processing": processing()}

    def portfolio(self, guru: str) -> dict[str, object]:
        return {"guru": guru, "info": {}, "holdings": [], "count": 0, "processing": processing()}

    def economic(self, indicators: str) -> dict[str, object]:
        return {"indicators": {indicators: {"latest_value": 3.0}}, "processing": processing()}

    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "name": name,
            "info": {"name": name, "type": "index", "description": "Macro", "currentValue": 1.0, "change": 0.0, "changePercent": 0.0},
            "seriesType": "line",
            "count": 1,
            "data": [],
            "processing": {**processing(), "requestedDepth": depth, "view": view},
        }

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return {"events": [], "count": 0, "month": month, "year": year, "categories": categories, "limit": limit, "processing": processing()}

    def fundamental_screen(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "moat": {"score": "wide"},
            "earnings_quality": {},
            "balance_sheet": {},
            "capital_allocation": {},
            "pricing_power": {},
            "warnings": [],
            "processing": processing(),
        }

    def risk_profile(self, name: str, *, depth: str = "auto") -> dict[str, object]:
        return {
            "ticker": name,
            "tail_risk": {},
            "convexity": {},
            "volatility": {"requestedDepth": depth},
            "drawdown": {},
            "warnings": [],
            "processing": processing(),
        }

    def valuation(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "dcf": {"status": "ready", "intrinsic_value": 120.0},
            "reverse_dcf": {"status": "ready", "implied_growth_pct": 8.0},
            "relative": {"trailing_pe": 22.0},
            "graham_number": 100.0,
            "margin_of_safety_pct": 12.0,
            "current_price": 107.0,
            "processing": processing(),
        }

    def sec_filings(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "cik": 1, "forms": [], "filings": [], "processing": processing()}

    def sec_filing_document(
        self, ticker: str, accession: str, primaryDocument: str, *, form: str = "10-Q"
    ) -> dict[str, object]:
        return {"ticker": ticker, "accession": accession, "primaryDocument": primaryDocument, "toc": [], "charCount": 0, "indexUrl": "", "documentUrl": "", "processing": processing()}

    def sec_filing_section(
        self, ticker: str, accession: str, primaryDocument: str, sectionSlug: str, *, form: str = "10-Q"
    ) -> dict[str, object]:
        return {"ticker": ticker, "accession": accession, "sectionSlug": sectionSlug, "sectionTitle": "stub", "markdown": "", "charCount": 0, "documentUrl": "", "processing": processing()}

    def fear_greed(self) -> dict[str, object]:
        return {"score": 50, "rating": "Neutral", "processing": processing()}

    def sp500_dcf(self) -> dict[str, object]:
        return {"status": "ready", "currentIntrinsicValue": 5000.0, "processing": processing()}

    def beta_estimate(self, ticker: str) -> dict[str, object]:
        return {"symbol": ticker, "beta": 1.0, "adjustedBeta": 1.0, "rSquared": 0.5, "processing": processing()}

    def top_companies(self) -> dict[str, object]:
        return {"companies": [], "count": 0, "processing": processing()}

    def market_regime(self) -> dict[str, object]:
        return {"summary": "stub", "confidence": "low", "signals": [], "processing": processing()}

    def trailing_forward_pe(self) -> dict[str, object]:
        return {"date": "2026-04-01", "latestValue": 0.0, "history": [], "processing": processing()}

    def market_breadth(self) -> dict[str, object]:
        return {"metrics": [], "processing": processing()}

    def watchlist(self) -> dict[str, object]:
        return {"items": [], "count": 0, "processing": processing()}


def fake_chart_opener(
    data_or_names,
    *,
    session_id: str | None = None,
    **kwargs,
) -> dict[str, object]:
    _ = kwargs
    return {
        "ok": True,
        "sessionId": session_id or "agent:chart",
        "chartUrl": f"http://127.0.0.1:8001/chart?sessionId={session_id or 'agent:chart'}",
        "processing": processing(),
        "inputEcho": data_or_names,
    }
