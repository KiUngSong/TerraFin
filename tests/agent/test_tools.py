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


def _adapter(agent_registry: TerraFinAgentDefinitionRegistry | None = None) -> TerraFinHostedToolAdapter:
    service = _FakeService()
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
    assert result.payload["taskId"] == result.task.task_id
    assert result.task.status in {"pending", "running", "completed"}
