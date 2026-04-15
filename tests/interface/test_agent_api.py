from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

import TerraFin.interface.agent.data_routes as agent_routes
import TerraFin.agent.service as agent_service
import TerraFin.interface.stock.data_routes as stock_routes
import TerraFin.interface.stock.payloads as stock_payloads
from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME, TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation, TerraFinHostedRunResult
from TerraFin.agent.runtime import TerraFinAgentSession, TerraFinTaskRegistry
from TerraFin.agent.session_store import (
    TerraFinHostedApprovalRequest,
    TerraFinHostedSessionRecord,
    TerraFinHostedViewContextRecord,
)
from TerraFin.agent.tools import TerraFinToolDefinition, TerraFinToolInvocationResult
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import SecEdgarConfigurationError
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app
from TerraFin.interface.watchlist_service import reset_watchlist_service


def _make_fake_tsdf(ticker: str = "TEST", n: int = 120) -> TimeSeriesDataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base = 100.0
    data = {
        "time": dates,
        "open": [base + idx * 0.1 for idx in range(n)],
        "high": [base + idx * 0.1 + 1 for idx in range(n)],
        "low": [base + idx * 0.1 - 1 for idx in range(n)],
        "close": [base + idx * 0.2 for idx in range(n)],
        "volume": [1000 + idx for idx in range(n)],
    }
    df = TimeSeriesDataFrame(pd.DataFrame(data))
    df.name = ticker
    return df


class _FakeDataFactory:
    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs

    def get(self, name):
        return _make_fake_tsdf(name, 180)

    def get_recent_history(self, name, period="3y"):
        _ = period
        df = _make_fake_tsdf(name, 90)
        return HistoryChunk(
            frame=df,
            loaded_start="2025-01-01",
            loaded_end="2025-05-06",
            requested_period="3y",
            is_complete=False,
            has_older=True,
            source_version="recent-cache",
        )

    def get_full_history_backfill(self, name, loaded_start=None):
        _ = loaded_start
        df = _make_fake_tsdf(name, 180)
        return HistoryChunk(
            frame=df,
            loaded_start="2024-07-03",
            loaded_end="2025-05-06",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="full-cache",
        )

    def get_fred_data(self, name):
        df = _make_fake_tsdf(name, 12)[["time", "close"]]
        df = TimeSeriesDataFrame(df)
        df.name = name
        return df

    def get_corporate_data(self, ticker, statement_type="income", period="annual"):
        _ = ticker, statement_type, period
        return pd.DataFrame(
            {
                "date": ["2025-12-31", "2024-12-31"],
                "Revenue": [1000.0, 950.0],
                "Net Income": [210.0, 200.0],
            }
        )


class _FakePrivateDataService:
    def get_market_breadth(self):
        return [{"label": "Advancers", "value": "300", "tone": "#047857"}]

    def get_calendar_events(self, *, year, month, categories=None, limit=None):
        _ = categories, limit
        return [
            {
                "id": f"{year}-{month}-1",
                "title": "CPI",
                "start": f"{year}-{month:02d}-12",
                "category": "macro",
                "importance": "high",
                "displayTime": "08:30",
                "description": "Inflation",
                "source": "FRED",
            }
        ]


class _FakeWatchlistService:
    def get_watchlist_snapshot(self):
        return [{"symbol": "AAPL", "name": "Apple", "move": "+1.1%"}]


class _FakePortfolioOutput:
    def __init__(self) -> None:
        self.info = {"Period": "Q1 2026", "Source": "fixture"}
        self.df = pd.DataFrame(
            [
                {"Stock": "AAA", "% of Portfolio": 10.5, "Recent Activity": "Add 2.00%", "Updated": 2.0},
                {"Stock": "BBB", "% of Portfolio": 8.0, "Recent Activity": "Reduce 1.50%", "Updated": -1.5},
            ]
        )


class _FakeHostedRuntime:
    def __init__(self, definition: TerraFinAgentDefinition) -> None:
        self._definition = definition
        self._records: dict[str, TerraFinHostedSessionRecord] = {}
        self._task_index: dict[str, str] = {}
        self._view_contexts: dict[str, TerraFinHostedViewContextRecord] = {}

    def list_agents(self):
        return (self._definition,)

    def create_record(self, session_id: str, *, metadata: dict | None = None) -> TerraFinHostedSessionRecord:
        session_metadata = {
            **dict(metadata or {}),
            "agentDefinition": self._definition.name,
            "agentPolicy": {
                "defaultDepth": self._definition.default_depth,
                "defaultView": self._definition.default_view,
                "chartAccess": self._definition.chart_access,
                "allowBackgroundTasks": self._definition.allow_background_tasks,
            },
        }
        session = TerraFinAgentSession(session_id=session_id, metadata=session_metadata)
        context = SimpleNamespace(session=session, task_registry=TerraFinTaskRegistry())
        record = TerraFinHostedSessionRecord(
            session_id=session_id,
            agent_name=self._definition.name,
            context=context,
            metadata=dict(session_metadata),
        )
        self._records[session_id] = record
        return record

    def get_session_record(self, session_id: str) -> TerraFinHostedSessionRecord:
        return self._records[session_id]

    def list_sessions(self):
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: record.last_accessed_at,
                reverse=True,
            )
        )

    def delete_session(self, session_id: str):
        record = self._records[session_id]
        active_tasks = [
            task
            for task in record.context.task_registry.list_for_session(session_id)
            if task.status not in {"completed", "failed", "cancelled"}
        ]
        if active_tasks:
            raise agent_routes.TerraFinAgentSessionConflictError(
                f"Session '{session_id}' still has active background tasks. Cancel them before deleting the session."
            )
        self._records.pop(session_id, None)
        return record

    def list_session_tasks(self, session_id: str):
        return self._records[session_id].context.task_registry.list_for_session(session_id)

    def get_task(self, task_id: str):
        session_id = self._task_index[task_id]
        return self._records[session_id].context.task_registry.get(task_id)

    def cancel_task(self, task_id: str):
        session_id = self._task_index[task_id]
        return self._records[session_id].context.task_registry.cancel(task_id, reason="Cancelled by test")

    def list_session_approvals(self, session_id: str):
        return tuple(self._records[session_id].approval_requests)

    def get_approval(self, approval_id: str):
        for record in self._records.values():
            for approval in record.approval_requests:
                if approval.approval_id == approval_id:
                    return approval
        raise KeyError(approval_id)

    def upsert_view_context(
        self,
        context_id: str,
        *,
        route: str,
        page_type: str,
        title: str | None = None,
        summary: str | None = None,
        selection: dict | None = None,
        entities: list[dict] | None = None,
        metadata: dict | None = None,
    ):
        existing = self._view_contexts.get(context_id)
        now = datetime.now(UTC)
        record = TerraFinHostedViewContextRecord(
            context_id=context_id,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            route=route,
            page_type=page_type,
            title=title,
            summary=summary,
            selection=dict(selection or {}),
            entities=[dict(entity) for entity in (entities or [])],
            metadata=dict(metadata or {}),
        )
        self._view_contexts[context_id] = record
        return record

    def get_view_context(self, context_id: str):
        return self._view_contexts[context_id]

    def approve_approval(self, approval_id: str, *, note: str | None = None):
        for record in self._records.values():
            for idx, approval in enumerate(record.approval_requests):
                if approval.approval_id != approval_id:
                    continue
                updated = replace(
                    approval,
                    status="approved",
                    updated_at=datetime.now(UTC),
                    resolved_at=datetime.now(UTC),
                    decision_note=note,
                )
                record.approval_requests[idx] = updated
                return updated
        raise KeyError(approval_id)

    def deny_approval(self, approval_id: str, *, note: str | None = None):
        for record in self._records.values():
            for idx, approval in enumerate(record.approval_requests):
                if approval.approval_id != approval_id:
                    continue
                updated = replace(
                    approval,
                    status="denied",
                    updated_at=datetime.now(UTC),
                    resolved_at=datetime.now(UTC),
                    decision_note=note,
                )
                record.approval_requests[idx] = updated
                return updated
        raise KeyError(approval_id)

    def seed_task(
        self,
        session_id: str,
        *,
        capability_name: str = "market_snapshot",
        description: str = "Fetch market snapshot",
        status: str = "running",
    ):
        record = self._records[session_id]
        task = record.context.task_registry.create(
            capability_name,
            description=description,
            session_id=session_id,
            input_payload={"name": "AAPL"},
        )
        if status == "running":
            task = record.context.task_registry.mark_running(task.task_id, progress={"stage": "queued"})
        elif status == "completed":
            record.context.task_registry.mark_running(task.task_id, progress={"stage": "queued"})
            task = record.context.task_registry.complete(
                task.task_id,
                result={"ticker": "AAPL"},
                progress={"stage": "done"},
            )
        self._task_index[task.task_id] = session_id
        return task

    def seed_approval(
        self,
        session_id: str,
        *,
        capability_name: str = "open_chart",
        tool_name: str = "open_chart",
    ):
        record = self._records[session_id]
        approval = TerraFinHostedApprovalRequest(
            approval_id="approval:test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            session_id=session_id,
            agent_name=self._definition.name,
            action="invoke",
            capability_name=capability_name,
            tool_name=tool_name,
            side_effecting=True,
            status="pending",
            reason="Human approval required before opening a chart.",
            fingerprint="fingerprint:test",
            input_payload={"data_or_names": ["AAPL"]},
        )
        record.approval_requests.append(approval)
        return approval


class _FakeHostedToolAdapter:
    def __init__(self, tools: tuple[TerraFinToolDefinition, ...]) -> None:
        self._tools = tools

    def list_tools_for_agent(self, agent_name: str):
        _ = agent_name
        return self._tools

    def list_tools_for_session(self, session_id: str):
        _ = session_id
        return self._tools


class _FakeHostedLoop:
    def __init__(self, *, runtime_configured: bool = True, runtime_setup_message: str | None = None) -> None:
        self.definition = TerraFinAgentDefinition(
            name=DEFAULT_HOSTED_AGENT_NAME,
            description="General market agent.",
            allowed_capabilities=("market_snapshot", "open_chart"),
            chart_access=True,
            allow_background_tasks=True,
        )
        self.tools = (
            TerraFinToolDefinition(
                name="market_snapshot",
                capability_name="market_snapshot",
                description="Fetch a compact market snapshot for a single asset.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                execution_mode="invoke",
                side_effecting=False,
            ),
        )
        self.runtime = _FakeHostedRuntime(self.definition)
        self.tool_adapter = _FakeHostedToolAdapter(self.tools)
        self._conversations: dict[str, TerraFinHostedConversation] = {}
        runtime_model = {
            "modelRef": "openai/gpt-4.1-mini",
            "providerId": "openai",
            "providerLabel": "OpenAI",
            "modelId": "gpt-4.1-mini",
            "metadata": {},
        }
        self.model_client = SimpleNamespace(
            describe_runtime_model=lambda session=None: runtime_model,
            describe_runtime_status=lambda session=None: {
                "runtimeModel": runtime_model,
                "configured": runtime_configured,
                "message": runtime_setup_message,
            },
        )

    def create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: dict | None = None,
        system_prompt: str | None = None,
    ) -> TerraFinHostedConversation:
        assert agent_name == self.definition.name
        record = self.runtime.create_record(session_id or "hosted:test-session", metadata=metadata)
        conversation = TerraFinHostedConversation(
            session_id=record.session_id,
            agent_name=agent_name,
            metadata=dict(metadata or {}),
            messages=[
                TerraFinConversationMessage(
                    role="system",
                    content=system_prompt or "You are a hosted TerraFin agent.",
                )
            ],
        )
        self._conversations[conversation.session_id] = conversation
        record.conversation = conversation
        return conversation

    def get_conversation(self, session_id: str) -> TerraFinHostedConversation:
        return self._conversations[session_id]

    def submit_user_message(self, session_id: str, content: str) -> TerraFinHostedRunResult:
        conversation = self._conversations[session_id]
        user_message = TerraFinConversationMessage(role="user", content=content)
        assistant_message = TerraFinConversationMessage(role="assistant", content="AAPL")
        conversation.messages.extend([user_message, assistant_message])
        tool_result = TerraFinToolInvocationResult(
            tool_name="market_snapshot",
            capability_name="market_snapshot",
            session_id=session_id,
            execution_mode="invoke",
            payload={"ticker": "AAPL"},
            task=None,
        )
        return TerraFinHostedRunResult(
            session_id=session_id,
            agent_name=conversation.agent_name,
            final_message=assistant_message,
            messages_added=(user_message, assistant_message),
            tool_results=(tool_result,),
            steps=2,
        )


def _configure_agent_fakes(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    monkeypatch.setattr(stock_payloads, "DataFactory", _FakeDataFactory)
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    monkeypatch.setattr(agent_service, "get_watchlist_service", lambda: _FakeWatchlistService())
    monkeypatch.setattr(
        stock_payloads,
        "get_ticker_info",
        lambda ticker: {
            "shortName": f"{ticker} Inc.",
            "sector": "Technology",
            "industry": "Software",
            "currentPrice": 150.0,
            "previousClose": 147.0,
            "exchange": "NASDAQ",
        },
    )
    monkeypatch.setattr(
        stock_payloads,
        "get_ticker_earnings",
        lambda ticker: [
            {
                "date": "2025-12-31",
                "epsEstimate": "2.10",
                "epsReported": "2.25",
                "surprise": "0.15",
                "surprisePercent": "7.14",
            }
        ],
    )
    monkeypatch.setattr(agent_service, "get_portfolio_data", lambda guru: _FakePortfolioOutput())


def _client(monkeypatch, *, hosted_loop=None) -> TestClient:
    _configure_agent_fakes(monkeypatch)
    if hosted_loop is not None:
        monkeypatch.setattr(agent_routes, "get_hosted_agent_loop", lambda: hosted_loop)
    reset_watchlist_service()
    reset_private_data_service()
    return TestClient(create_app())


def test_agent_market_data_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/market-data?ticker=TEST&depth=auto&view=monthly")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "seriesType", "count", "data", "processing"}
    assert payload["ticker"] == "TEST"
    assert payload["processing"]["requestedDepth"] == "auto"
    assert payload["processing"]["resolvedDepth"] == "recent"
    assert payload["processing"]["view"] == "monthly"


def test_agent_indicators_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/indicators?ticker=TEST&indicators=rsi,macd,bb,sma_20,realized_vol,range_vol")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "indicators", "unknown", "processing"}
    assert set(payload["indicators"]) == {"rsi", "macd", "bb", "sma_20", "realized_vol", "range_vol"}
    assert payload["unknown"] == []
    assert payload["processing"]["resolvedDepth"] == "recent"


def test_agent_market_snapshot_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/market-snapshot?ticker=TEST&depth=full")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "price_action", "indicators", "market_breadth", "watchlist", "processing"}
    assert payload["processing"]["resolvedDepth"] == "full"
    assert payload["watchlist"][0]["symbol"] == "AAPL"


def test_agent_resolve_company_earnings_and_financials(monkeypatch) -> None:
    client = _client(monkeypatch)

    resolve_resp = client.get("/agent/api/resolve?q=AAPL")
    company_resp = client.get("/agent/api/company?ticker=AAPL")
    earnings_resp = client.get("/agent/api/earnings?ticker=AAPL")
    financials_resp = client.get("/agent/api/financials?ticker=AAPL&statement=income&period=annual")

    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["path"] == "/stock/AAPL"

    assert company_resp.status_code == 200
    assert company_resp.json()["ticker"] == "AAPL"
    assert "processing" in company_resp.json()

    assert earnings_resp.status_code == 200
    assert earnings_resp.json()["earnings"][0]["epsReported"] == "2.25"

    assert financials_resp.status_code == 200
    assert financials_resp.json()["statement"] == "income"
    assert len(financials_resp.json()["rows"]) == 2


def test_agent_portfolio_economic_macro_and_calendar(monkeypatch) -> None:
    client = _client(monkeypatch)

    portfolio_resp = client.get("/agent/api/portfolio?guru=Test%20Guru")
    economic_resp = client.get("/agent/api/economic?indicators=UNRATE")
    macro_resp = client.get("/agent/api/macro-focus?name=S%26P%20500&view=weekly")
    china_macro_resp = client.get("/agent/api/macro-focus?name=Shanghai%20Composite&view=weekly")
    calendar_resp = client.get("/agent/api/calendar?year=2026&month=4&categories=macro")

    assert portfolio_resp.status_code == 200
    assert portfolio_resp.json()["count"] == 2

    assert economic_resp.status_code == 200
    assert "UNRATE" in economic_resp.json()["indicators"]
    assert "processing" in economic_resp.json()

    assert macro_resp.status_code == 200
    assert macro_resp.json()["info"]["type"] == "index"
    assert macro_resp.json()["info"]["description"] == "Benchmark U.S. large-cap equity index."
    assert macro_resp.json()["processing"]["view"] == "weekly"

    assert china_macro_resp.status_code == 200
    assert china_macro_resp.json()["name"] == "Shanghai Composite"
    assert china_macro_resp.json()["info"]["type"] == "index"
    assert china_macro_resp.json()["info"]["description"] == (
        "Broad mainland China equity benchmark tracking the Shanghai market."
    )

    assert calendar_resp.status_code == 200
    assert calendar_resp.json()["count"] == 1
    assert calendar_resp.json()["processing"]["resolvedDepth"] == "full"


def test_agent_openapi_includes_new_routes(monkeypatch) -> None:
    client = _client(monkeypatch, hosted_loop=_FakeHostedLoop())

    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/agent/api/resolve" in paths
    assert "/agent/api/company" in paths
    assert "/agent/api/earnings" in paths
    assert "/agent/api/financials" in paths
    assert "/agent/api/macro-focus" in paths
    assert "/agent/api/calendar" in paths
    assert "/agent/api/runtime/agents" in paths
    assert "/agent/api/runtime/sessions" in paths
    assert "/agent/api/runtime/sessions/{session_id}" in paths
    assert "/agent/api/runtime/view-contexts/{context_id}" in paths
    assert "/agent/api/runtime/sessions/{session_id}/messages" in paths
    assert "/agent/api/runtime/sessions/{session_id}/tasks" in paths
    assert "/agent/api/runtime/sessions/{session_id}/approvals" in paths
    assert "/agent/api/runtime/tasks/{task_id}" in paths
    assert "/agent/api/runtime/approvals/{approval_id}" in paths
    assert "/agent/api/runtime/approvals/{approval_id}/approve" in paths
    assert "/agent/api/runtime/approvals/{approval_id}/deny" in paths


def test_agent_portfolio_returns_503_when_sec_edgar_is_not_configured(monkeypatch) -> None:
    _configure_agent_fakes(monkeypatch)
    monkeypatch.setattr(
        agent_service,
        "get_portfolio_data",
        lambda guru: (_ for _ in ()).throw(
            SecEdgarConfigurationError(
                "SEC EDGAR access is unavailable until `TERRAFIN_SEC_USER_AGENT` is configured."
            )
        ),
    )
    reset_watchlist_service()
    reset_private_data_service()
    client = TestClient(create_app())

    response = client.get("/agent/api/portfolio?guru=Warren%20Buffett")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "sec_edgar_not_configured"
    assert payload["error"]["details"]["feature"] == "agent_portfolio"


def test_hosted_agent_runtime_routes(monkeypatch) -> None:
    loop = _FakeHostedLoop()
    client = _client(monkeypatch, hosted_loop=loop)

    catalog = client.get("/agent/api/runtime/agents")
    assert catalog.status_code == 200
    catalog_payload = catalog.json()
    assert catalog_payload["agents"][0]["name"] == DEFAULT_HOSTED_AGENT_NAME
    assert catalog_payload["agents"][0]["tools"][0]["name"] == "market_snapshot"
    assert catalog_payload["agents"][0]["runtimeModel"]["modelRef"] == "openai/gpt-4.1-mini"
    assert catalog_payload["agents"][0]["runtimeConfigured"] is True
    assert catalog_payload["agents"][0]["runtimeSetupMessage"] is None

    create_resp = client.post(
        "/agent/api/runtime/sessions",
        json={
            "agentName": DEFAULT_HOSTED_AGENT_NAME,
            "sessionId": "hosted:http-test",
            "metadata": {"thread": "demo"},
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["sessionId"] == "hosted:http-test"
    assert created["agentName"] == DEFAULT_HOSTED_AGENT_NAME
    assert created["metadata"]["thread"] == "demo"
    assert created["runtimeModel"]["providerId"] == "openai"
    assert created["messages"][0]["role"] == "system"

    session_resp = client.get("/agent/api/runtime/sessions/hosted:http-test")
    assert session_resp.status_code == 200
    assert session_resp.json()["sessionId"] == "hosted:http-test"
    assert session_resp.json()["runtimeModel"]["modelId"] == "gpt-4.1-mini"

    sessions_resp = client.get("/agent/api/runtime/sessions")
    assert sessions_resp.status_code == 200
    sessions_payload = sessions_resp.json()
    assert sessions_payload["sessions"][0]["sessionId"] == "hosted:http-test"
    assert sessions_payload["sessions"][0]["messageCount"] == 0

    view_context_resp = client.put(
        "/agent/api/runtime/view-contexts/view:buffett",
        json={
            "route": "/market-insights",
            "pageType": "market-insights",
            "title": "Warren Buffett Portfolio View",
            "selection": {"selectedGuru": "Warren Buffett"},
            "entities": [{"kind": "portfolio", "id": "Warren Buffett"}],
        },
    )
    assert view_context_resp.status_code == 200
    assert view_context_resp.json()["contextId"] == "view:buffett"
    assert view_context_resp.json()["selection"]["selectedGuru"] == "Warren Buffett"

    get_view_context_resp = client.get("/agent/api/runtime/view-contexts/view:buffett")
    assert get_view_context_resp.status_code == 200
    assert get_view_context_resp.json()["pageType"] == "market-insights"

    run_resp = client.post(
        "/agent/api/runtime/sessions/hosted:http-test/messages",
        json={"content": "Give me AAPL."},
    )
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    assert run_payload["steps"] == 2
    assert run_payload["finalMessage"]["content"] == "AAPL"
    assert run_payload["toolResults"][0]["toolName"] == "market_snapshot"
    assert run_payload["session"]["messages"][-1]["role"] == "assistant"

    task = loop.runtime.seed_task("hosted:http-test")

    task_list_resp = client.get("/agent/api/runtime/sessions/hosted:http-test/tasks")
    assert task_list_resp.status_code == 200
    assert task_list_resp.json()["tasks"][0]["taskId"] == task.task_id

    task_resp = client.get(f"/agent/api/runtime/tasks/{task.task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "running"

    cancel_resp = client.post(f"/agent/api/runtime/tasks/{task.task_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    approval = loop.runtime.seed_approval("hosted:http-test")

    approval_list_resp = client.get("/agent/api/runtime/sessions/hosted:http-test/approvals")
    assert approval_list_resp.status_code == 200
    assert approval_list_resp.json()["approvals"][0]["approvalId"] == approval.approval_id

    approval_resp = client.get(f"/agent/api/runtime/approvals/{approval.approval_id}")
    assert approval_resp.status_code == 200
    assert approval_resp.json()["status"] == "pending"

    approve_resp = client.post(
        f"/agent/api/runtime/approvals/{approval.approval_id}/approve",
        json={"note": "Ship it"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    deny_resp = client.post(
        f"/agent/api/runtime/approvals/{approval.approval_id}/deny",
        json={"note": "Actually no"},
    )
    assert deny_resp.status_code == 200
    assert deny_resp.json()["status"] == "denied"

    loop.runtime.seed_task("hosted:http-test")
    delete_conflict_resp = client.delete("/agent/api/runtime/sessions/hosted:http-test")
    assert delete_conflict_resp.status_code == 409

    completed_task = loop.runtime.seed_task("hosted:http-test", status="completed")
    assert completed_task.status == "completed"
    for task_record in loop.runtime.get_session_record("hosted:http-test").context.task_registry.list_for_session("hosted:http-test"):
        if task_record.status not in {"completed", "failed", "cancelled"}:
            loop.runtime.get_session_record("hosted:http-test").context.task_registry.cancel(
                task_record.task_id,
                reason="Settled for delete test",
            )

    delete_resp = client.delete("/agent/api/runtime/sessions/hosted:http-test")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["sessionId"] == "hosted:http-test"

    deleted_session_resp = client.get("/agent/api/runtime/sessions/hosted:http-test")
    assert deleted_session_resp.status_code == 404


def test_hosted_agent_runtime_routes_report_unconfigured_runtime(monkeypatch) -> None:
    loop = _FakeHostedLoop(
        runtime_configured=False,
        runtime_setup_message="OPENAI_API_KEY is required for the hosted OpenAI agent runtime.",
    )
    client = _client(monkeypatch, hosted_loop=loop)

    catalog = client.get("/agent/api/runtime/agents")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["agents"][0]["runtimeConfigured"] is False
    assert payload["agents"][0]["runtimeSetupMessage"] == (
        "OPENAI_API_KEY is required for the hosted OpenAI agent runtime."
    )

    create_resp = client.post(
        "/agent/api/runtime/sessions",
        json={
            "agentName": DEFAULT_HOSTED_AGENT_NAME,
            "sessionId": "hosted:http-test",
        },
    )
    assert create_resp.status_code == 503
    assert create_resp.json()["error"]["code"] == "hosted_agent_not_configured"


def test_agent_page_route_is_not_registered(monkeypatch) -> None:
    client = _client(monkeypatch, hosted_loop=_FakeHostedLoop())

    response = client.get("/agent")

    assert response.status_code == 404
