import pytest

from TerraFin.agent.definitions import (
    DEFAULT_HOSTED_AGENT_NAME,
    TerraFinAgentDefinition,
    TerraFinAgentDefinitionRegistry,
)
from TerraFin.agent.hosted_runtime import TerraFinHostedAgentRuntime
from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.tools import TerraFinHostedToolAdapter


def _processing() -> dict[str, object]:
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


class _FakeService:
    def resolve(self, query: str) -> dict[str, object]:
        return {"type": "stock", "name": query.upper(), "path": f"/stock/{query.upper()}", "processing": _processing()}

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"ticker": name, "seriesType": "candlestick", "count": 1, "data": [], "processing": {**_processing(), "requestedDepth": depth, "view": view}}

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
            "processing": {**_processing(), "requestedDepth": depth, "view": view, "indicatorQuery": indicators},
        }

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "ticker": name,
            "price_action": {"current": 100.0},
            "indicators": {"rsi": 55.0},
            "market_breadth": [],
            "watchlist": [],
            "processing": {**_processing(), "requestedDepth": depth, "view": view},
        }

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"name": name, "confidence": 0.2, "processing": {**_processing(), "requestedDepth": depth, "view": view}}

    def company_info(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "shortName": f"{ticker} Corp", "processing": _processing()}

    def earnings(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "earnings": [], "processing": _processing()}

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, object]:
        return {"ticker": ticker, "statement": statement, "period": period, "columns": [], "rows": [], "processing": _processing()}

    def portfolio(self, guru: str) -> dict[str, object]:
        return {"guru": guru, "info": {}, "holdings": [], "count": 0, "processing": _processing()}

    def economic(self, indicators: str) -> dict[str, object]:
        return {"indicators": {indicators: {"latest_value": 3.0}}, "processing": _processing()}

    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "name": name,
            "info": {"name": name, "type": "index", "description": "Macro", "currentValue": 1.0, "change": 0.0, "changePercent": 0.0},
            "seriesType": "line",
            "count": 1,
            "data": [],
            "processing": {**_processing(), "requestedDepth": depth, "view": view},
        }

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return {"events": [], "count": 0, "month": month, "year": year, "categories": categories, "limit": limit, "processing": _processing()}

    def fundamental_screen(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "moat": {"score": "wide"},
            "earnings_quality": {},
            "balance_sheet": {},
            "capital_allocation": {},
            "pricing_power": {},
            "warnings": [],
            "processing": _processing(),
        }

    def risk_profile(self, name: str, *, depth: str = "auto") -> dict[str, object]:
        return {
            "ticker": name,
            "tail_risk": {},
            "convexity": {},
            "volatility": {"requestedDepth": depth},
            "drawdown": {},
            "warnings": [],
            "processing": _processing(),
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
            "processing": _processing(),
        }

    def sec_filings(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "cik": 1, "forms": ["10-K"], "filings": [], "processing": _processing()}

    def sec_filing_document(
        self, ticker: str, accession: str, primaryDocument: str, *, form: str = "10-Q"
    ) -> dict[str, object]:
        return {
            "ticker": ticker,
            "accession": accession,
            "primaryDocument": primaryDocument,
            "toc": [],
            "charCount": 0,
            "indexUrl": "",
            "documentUrl": "",
            "processing": _processing(),
        }

    def sec_filing_section(
        self,
        ticker: str,
        accession: str,
        primaryDocument: str,
        sectionSlug: str,
        *,
        form: str = "10-Q",
    ) -> dict[str, object]:
        return {
            "ticker": ticker,
            "accession": accession,
            "sectionSlug": sectionSlug,
            "sectionTitle": "stub",
            "markdown": "",
            "charCount": 0,
            "documentUrl": "",
            "processing": _processing(),
        }

    def fear_greed(self) -> dict[str, object]:
        return {"score": 50, "rating": "Neutral", "processing": _processing()}

    def sp500_dcf(self) -> dict[str, object]:
        return {"status": "ready", "currentIntrinsicValue": 5000.0, "processing": _processing()}

    def beta_estimate(self, ticker: str) -> dict[str, object]:
        return {"symbol": ticker, "beta": 1.0, "adjustedBeta": 1.0, "rSquared": 0.5, "processing": _processing()}

    def top_companies(self) -> dict[str, object]:
        return {"companies": [], "count": 0, "processing": _processing()}

    def market_regime(self) -> dict[str, object]:
        return {"summary": "stub", "confidence": "low", "signals": [], "processing": _processing()}

    def trailing_forward_pe(self) -> dict[str, object]:
        return {"date": "2026-04-01", "latestValue": 0.0, "history": [], "processing": _processing()}

    def market_breadth(self) -> dict[str, object]:
        return {"metrics": [], "processing": _processing()}

    def watchlist(self) -> dict[str, object]:
        return {"items": [], "count": 0, "processing": _processing()}


class _RetryingFakeService(_FakeService):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        self.calls.append(name)
        if name == "NASDAQ COMPOSITE":
            raise ValueError("Invalid ticker: NASDAQ COMPOSITE")
        return super().market_snapshot(name, depth=depth, view=view)


class _UnrepairableRecoverableErrorService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        raise ValueError(f"Invalid ticker: {name}")


class _QuotaFailureService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        raise RuntimeError("429 rate limit exceeded for upstream API key")


class _MacroFocusEquityMisuseService(_FakeService):
    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        raise LookupError(f"Unknown macro instrument: '{name}'")


def _fake_chart_opener(
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
        "processing": _processing(),
        "inputEcho": data_or_names,
    }


def _adapter(
    agent_registry: TerraFinAgentDefinitionRegistry | None = None,
    *,
    service: _FakeService | None = None,
) -> TerraFinHostedToolAdapter:
    service = service or _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    runtime = TerraFinHostedAgentRuntime(service=service, capability_registry=registry, agent_registry=agent_registry)
    return TerraFinHostedToolAdapter(runtime)


def test_list_tools_for_agent_filters_by_definition_and_exposes_task_variants() -> None:
    adapter = _adapter()
    restricted_adapter = _adapter(
        TerraFinAgentDefinitionRegistry(
            [
                TerraFinAgentDefinition(
                    name="portfolio-reader",
                    description="Portfolio-only test agent.",
                    allowed_capabilities=("portfolio", "company_info", "market_snapshot"),
                    default_depth="auto",
                    default_view="daily",
                    chart_access=False,
                    allow_background_tasks=True,
                )
            ]
        )
    )

    market_tool_names = tuple(tool.name for tool in adapter.list_tools_for_agent(DEFAULT_HOSTED_AGENT_NAME))
    portfolio_tool_names = tuple(tool.name for tool in restricted_adapter.list_tools_for_agent("portfolio-reader"))

    assert "market_snapshot" in market_tool_names
    assert "start_market_snapshot_task" in market_tool_names
    assert "open_chart" in market_tool_names
    assert "economic" in market_tool_names
    assert "portfolio" in portfolio_tool_names
    assert "open_chart" not in portfolio_tool_names


def test_function_tool_schema_is_model_ready() -> None:
    adapter = _adapter()

    tool = adapter.get_tool_for_agent(DEFAULT_HOSTED_AGENT_NAME, "market_snapshot")
    payload = tool.as_function_tool()

    assert payload["type"] == "function"
    assert payload["function"]["name"] == "market_snapshot"
    parameters = payload["function"]["parameters"]
    assert parameters["type"] == "object"
    assert "name" in parameters["required"]
    assert parameters["properties"]["depth"]["enum"] == ["auto", "recent", "full"]
    assert parameters["properties"]["view"]["enum"] == ["daily", "weekly", "monthly", "yearly"]


def test_run_tool_invokes_runtime_with_agent_defaults() -> None:
    adapter = _adapter(
        TerraFinAgentDefinitionRegistry(
            [
                TerraFinAgentDefinition(
                    name="macro-analyst",
                    description="Macro-focused test agent.",
                    allowed_capabilities=("macro_focus",),
                    default_depth="auto",
                    default_view="weekly",
                    chart_access=False,
                    allow_background_tasks=False,
                )
            ]
        )
    )
    session = adapter.runtime.create_session("macro-analyst", session_id="tool:macro")

    result = adapter.run_tool(session.session.session_id, "macro_focus", {"name": "DXY"})

    assert result.execution_mode == "invoke"
    assert result.payload["processing"]["requestedDepth"] == "auto"
    assert result.payload["processing"]["view"] == "weekly"


def test_run_tool_binds_open_chart_to_hosted_session() -> None:
    adapter = _adapter()
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:chart")

    result = adapter.run_tool(session.session.session_id, "open_chart", {"data_or_names": ["AAPL", "MSFT"]})

    assert result.payload["sessionId"] == "tool:chart"
    assert result.payload["chartUrl"].endswith("sessionId=tool:chart")


def test_run_tool_can_start_background_task_variant() -> None:
    adapter = _adapter()
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:task")

    result = adapter.run_tool(session.session.session_id, "start_market_snapshot_task", {"name": "MSFT"})

    assert result.execution_mode == "task"
    assert result.task is not None
    assert result.payload["accepted"] is True


def test_run_tool_retries_with_repaired_macro_alias_before_exposing_error() -> None:
    service = _RetryingFakeService()
    adapter = _adapter(service=service)
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:retry")

    result = adapter.run_tool(session.session.session_id, "market_snapshot", {"name": "NASDAQ COMPOSITE"})

    assert result.payload["ticker"] == "Nasdaq"
    assert service.calls == ["NASDAQ COMPOSITE", "Nasdaq"]


class _SecFilingSlugNotFoundService(_FakeService):
    """Service fake where sec_filing_section raises the exact LookupError
    shape the real service emits when the slug isn't in the TOC."""

    def sec_filing_section(
        self,
        ticker: str,
        accession: str,
        primaryDocument: str,
        sectionSlug: str,
        *,
        form: str = "10-Q",
    ) -> dict[str, object]:
        raise LookupError(
            f"Section '{sectionSlug}' not found. "
            "Do NOT report 'section doesn't exist' — retry this tool with one of the available "
            "slugs. The 5 largest sections in this filing are: "
            "item-6-reserved (213068 chars, 'Item 6. Reserved.'), "
            "item-1-business (180091 chars, 'Item 1. Business.'), "
            "part-ii (218055 chars, 'Part II'), "
            "part-i (185218 chars, 'PART I'), "
            "item-3-legal-proceedings (4203 chars, 'Item 3. Legal Proceedings.'). "
            "All 7 available slugs: part-i, item-1-business, item-2-properties, "
            "item-3-legal-proceedings, part-ii, item-5-market, item-6-reserved"
        )


def test_run_tool_classifies_sec_filing_section_bad_slug_as_retryable() -> None:
    """The `sec_filing_section` service raises a rich LookupError with
    the full TOC slug list and explicit retry guidance. Without the
    classifier recognizing it, the exception propagates raw — the model
    sees an unstructured error, paraphrases it, and gives up instead
    of retrying with a valid slug (the exact ZETA 10-K failure mode).

    Regression for QA-identified CRITICAL #2."""
    adapter = _adapter(service=_SecFilingSlugNotFoundService())
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:sec-slug-not-found")

    result = adapter.run_tool(
        session.session.session_id,
        "sec_filing_section",
        {
            "ticker": "ZETA",
            "accession": "0000000000-26-000000",
            "primaryDocument": "zeta.htm",
            "sectionSlug": "financial-statements",  # bad guess, not in TOC
            "form": "10-K",
        },
    )

    assert result.is_error is True
    assert result.retryable is True
    assert result.error_code == "sec_filing_section_slug_not_found"
    assert result.payload["accepted"] is False
    assert result.payload["error"]["retryable"] is True
    # Model hint must tell the LLM to retry and include the full slug list.
    hint = result.payload["error"]["modelHint"]
    assert "DO NOT tell the user" in hint
    assert "item-6-reserved" in hint  # largest slug surfaced
    assert "part-ii" in hint  # Part II reference for 10-K earnings guidance
    assert "MD&A" in hint or "earnings" in hint  # earnings/MD&A hint


def test_run_tool_returns_internal_retryable_error_result_for_symbol_resolution_failures() -> None:
    adapter = _adapter(service=_UnrepairableRecoverableErrorService())
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:recoverable-error")

    result = adapter.run_tool(session.session.session_id, "market_snapshot", {"name": "CURRENT MARKET STATE"})

    assert result.is_error is True
    assert result.retryable is True
    assert result.error_code == "tool_input_resolution_error"
    assert result.payload["accepted"] is False
    assert result.payload["error"]["retryable"] is True
    assert "descriptive phrase" in result.payload["error"]["message"]
    assert "current_view_context" in result.payload["error"]["modelHint"]


def test_run_tool_guides_macro_focus_away_from_equity_index_etfs() -> None:
    adapter = _adapter(service=_MacroFocusEquityMisuseService())
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:macro-misuse")

    result = adapter.run_tool(session.session.session_id, "macro_focus", {"name": "SPY"})

    assert result.is_error is True
    assert result.retryable is True
    assert result.error_code == "tool_wrong_market_tool"
    assert "equity index or ETF" in result.payload["error"]["message"]
    assert "market_snapshot" in result.payload["error"]["modelHint"]


def test_run_tool_repairs_common_index_aliases_to_supported_etfs() -> None:
    adapter = _adapter()
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:index-alias")

    result = adapter.run_tool(session.session.session_id, "market_snapshot", {"name": "SPX"})

    assert result.payload["ticker"] == "SPY"


def test_run_tool_blocks_operating_business_tools_for_benchmark_etfs() -> None:
    adapter = _adapter()
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:benchmark-business-misuse")

    result = adapter.run_tool(session.session.session_id, "fundamental_screen", {"ticker": "SPY"})

    assert result.is_error is True
    assert result.retryable is True
    assert result.error_code == "tool_wrong_equity_benchmark_analysis"
    assert "operating-business ticker" in result.payload["error"]["message"]
    assert "fundamental_screen" in result.payload["error"]["modelHint"]


def test_run_tool_still_raises_for_upstream_auth_or_quota_failures() -> None:
    adapter = _adapter(service=_QuotaFailureService())
    session = adapter.runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:quota-error")

    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        adapter.run_tool(session.session.session_id, "market_snapshot", {"name": "AAPL"})
