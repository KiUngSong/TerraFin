import pytest

import TerraFin.agent.runtime as agent_runtime


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


class _ExplodingService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        _ = name, depth, view
        raise RuntimeError("snapshot failed")


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


def test_default_capability_registry_contains_kernel_capabilities() -> None:
    registry = agent_runtime.build_default_capability_registry(_FakeService(), chart_opener=_fake_chart_opener)

    assert registry.names() == (
        "resolve",
        "market_data",
        "indicators",
        "market_snapshot",
        "lppl_analysis",
        "company_info",
        "earnings",
        "financials",
        "portfolio",
        "economic",
        "macro_focus",
        "calendar_events",
        "open_chart",
        "fundamental_screen",
        "risk_profile",
        "valuation",
    )


def test_context_call_records_focus_and_capability_history() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    payload = context.call("market_snapshot", name="AAPL", depth="auto", view="weekly")

    assert payload["ticker"] == "AAPL"
    snapshot = context.session.snapshot()
    assert snapshot.focus_items == ("AAPL",)
    assert len(snapshot.capability_calls) == 1
    assert snapshot.capability_calls[0].capability_name == "market_snapshot"
    assert "processing" in snapshot.capability_calls[0].output_keys


def test_context_call_records_chart_artifact() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    payload = context.call("open_chart", data_or_names=["AAPL", "MSFT"], session_id="agent:test-chart")

    assert payload["ok"] is True
    snapshot = context.session.snapshot()
    assert snapshot.focus_items == ("AAPL", "MSFT")
    assert len(snapshot.artifacts) == 1
    artifact = snapshot.artifacts[0]
    assert artifact.kind == "chart"
    assert artifact.artifact_id == "agent:test-chart"
    assert artifact.title == "Chart: AAPL, MSFT"


def test_run_task_completes_and_persists_result() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    task, result = context.run_task("company_info", ticker="MSFT", description="load company profile")

    assert result["ticker"] == "MSFT"
    assert task.status == "completed"
    stored = context.task_registry.get(task.task_id)
    assert stored.status == "completed"
    assert stored.result is not None
    assert stored.result["ticker"] == "MSFT"


def test_run_task_marks_failure_when_capability_raises() -> None:
    context = agent_runtime.create_agent_context(
        service=_ExplodingService(),
        chart_opener=_fake_chart_opener,
    )

    with pytest.raises(RuntimeError, match="snapshot failed"):
        context.run_task("market_snapshot", name="NVDA")

    tasks = context.task_registry.list()
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert tasks[0].error == "snapshot failed"
