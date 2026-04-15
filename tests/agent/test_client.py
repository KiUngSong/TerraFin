import pandas as pd

import TerraFin.agent.client as agent_client
from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME, TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation, TerraFinHostedRunResult
from TerraFin.agent.tools import TerraFinToolDefinition, TerraFinToolInvocationResult
from TerraFin.data.contracts import TimeSeriesDataFrame


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return dict(self._payload)


class _FakeService:
    def resolve(self, query: str):
        return {"query": query, "mode": "python"}

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily"):
        return {"ticker": name, "depth": depth, "view": view, "mode": "python"}


class _FakeHostedRuntime:
    def __init__(self) -> None:
        self._definition = TerraFinAgentDefinition(
            name=DEFAULT_HOSTED_AGENT_NAME,
            description="General market agent.",
            allowed_capabilities=("market_snapshot", "open_chart"),
            chart_access=True,
            allow_background_tasks=True,
        )
        self._records: dict[str, object] = {}

    def list_agents(self):
        return (self._definition,)

    def list_sessions(self):
        return tuple(self._records.values())

    def delete_session(self, session_id: str):
        return self._records.pop(session_id)


class _FakeHostedToolAdapter:
    def __init__(self) -> None:
        self._tools = (
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

    def list_tools_for_agent(self, agent_name: str):
        _ = agent_name
        return self._tools

    def list_tools_for_session(self, session_id: str):
        _ = session_id
        return self._tools


class _FakeHostedLoop:
    def __init__(self) -> None:
        self.runtime = _FakeHostedRuntime()
        self.tool_adapter = _FakeHostedToolAdapter()
        self._conversations: dict[str, TerraFinHostedConversation] = {}
        self.model_client = type("ModelClient", (), {"describe_runtime_model": staticmethod(lambda session=None: None)})()

    def create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: dict | None = None,
        system_prompt: str | None = None,
    ) -> TerraFinHostedConversation:
        conversation = TerraFinHostedConversation(
            session_id=session_id or "runtime:test",
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
        self.runtime._records[conversation.session_id] = _FakeHostedRecord(conversation)
        return conversation

    def get_conversation(self, session_id: str) -> TerraFinHostedConversation:
        return self._conversations[session_id]

    def submit_user_message(self, session_id: str, content: str) -> TerraFinHostedRunResult:
        conversation = self._conversations[session_id]
        user_message = TerraFinConversationMessage(role="user", content=content)
        assistant_message = TerraFinConversationMessage(role="assistant", content="AAPL")
        conversation.messages.extend([user_message, assistant_message])
        result = TerraFinToolInvocationResult(
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
            tool_results=(result,),
            steps=2,
        )


class _FakeHostedRecord:
    def __init__(self, conversation: TerraFinHostedConversation) -> None:
        self.session_id = conversation.session_id
        self.agent_name = conversation.agent_name
        self.created_at = conversation.created_at
        self.updated_at = conversation.created_at
        self.last_accessed_at = conversation.created_at
        self.conversation = conversation
        self.context = type(
            "Context",
            (),
            {
                "session": type("Session", (), {"metadata": {}})(),
                "task_registry": type("TaskRegistry", (), {"list_for_session": staticmethod(lambda session_id: ())})(),
            },
        )()


def test_auto_transport_prefers_python_when_no_base_url(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    client = agent_client.TerraFinAgentClient()

    payload = client.market_data("AAPL", depth="recent", view="weekly")

    assert payload == {"ticker": "AAPL", "depth": "recent", "view": "weekly", "mode": "python"}


def test_http_transport_uses_agent_api_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    request_log: list[tuple[str, dict | None]] = []

    def _fake_get(url: str, params: dict | None = None, timeout: float = 0):
        _ = timeout
        request_log.append((url, params))
        return _FakeResponse(200, {"ok": True, "path": url, "params": params})

    monkeypatch.setattr(agent_client.requests, "get", _fake_get)
    client = agent_client.TerraFinAgentClient(transport="http", base_url="http://127.0.0.1:8001")

    payload = client.market_data("AAPL", depth="full", view="monthly")

    assert request_log == [
        (
            "http://127.0.0.1:8001/agent/api/market-data",
            {"ticker": "AAPL", "depth": "full", "view": "monthly"},
        )
    ]
    assert payload["ok"] is True


def test_open_chart_remote_names_uses_chart_routes(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    request_log: list[tuple[str, dict, dict | None]] = []

    def _fake_post(url: str, json: dict, headers: dict | None = None, timeout: float = 0):
        _ = timeout
        request_log.append((url, json, headers))
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(agent_client.requests, "post", _fake_post)
    client = agent_client.TerraFinAgentClient(transport="http", base_url="http://127.0.0.1:8001")

    payload = client.open_chart(["S&P 500", "Nasdaq"], session_id="agent:test")

    assert request_log == [
        (
            "http://127.0.0.1:8001/chart/api/chart-series/progressive/set",
            {"name": "S&P 500", "pinned": True, "seedPeriod": "3y"},
            {"X-Session-ID": "agent:test"},
        ),
        (
            "http://127.0.0.1:8001/chart/api/chart-series/add",
            {"name": "Nasdaq"},
            {"X-Session-ID": "agent:test"},
        ),
    ]
    assert payload["chartUrl"] == "http://127.0.0.1:8001/chart?sessionId=agent:test"


def test_open_chart_local_frames_reuses_chart_client(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    monkeypatch.setattr(agent_client.chart_client, "_wait_for_server_ready", lambda timeout_s=0, poll_interval_s=0: True)
    monkeypatch.setattr(agent_client.chart_client, "start_server", lambda: 1234)
    monkeypatch.setattr(agent_client.chart_client, "update_chart", lambda data, session_id=None: True)
    monkeypatch.setattr(
        agent_client.chart_client,
        "_runtime_chart_url",
        lambda path, session_id=None: f"http://127.0.0.1:8001{path}?sessionId={session_id}",
    )

    df = TimeSeriesDataFrame(pd.DataFrame({"time": ["2026-01-01"], "close": [100.0]}))
    client = agent_client.TerraFinAgentClient(transport="python")

    payload = client.open_chart(df, session_id="agent:frame")

    assert payload["ok"] is True
    assert payload["chartUrl"] == "http://127.0.0.1:8001/chart?sessionId=agent:frame"


def test_runtime_python_transport_uses_hosted_loop(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    fake_loop = _FakeHostedLoop()
    monkeypatch.setattr(agent_client.TerraFinAgentClient, "_runtime_loop", lambda self: fake_loop)
    client = agent_client.TerraFinAgentClient(transport="python")

    catalog = client.runtime_agents()
    session = client.runtime_create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="runtime:python")
    sessions = client.runtime_sessions()
    run = client.runtime_message("runtime:python", "Give me AAPL.")
    deleted = client.runtime_delete_session("runtime:python")

    assert catalog["agents"][0]["name"] == DEFAULT_HOSTED_AGENT_NAME
    assert session["sessionId"] == "runtime:python"
    assert session["tools"][0]["name"] == "market_snapshot"
    assert sessions["sessions"][0]["sessionId"] == "runtime:python"
    assert run["finalMessage"]["content"] == "AAPL"
    assert run["session"]["messages"][-1]["role"] == "assistant"
    assert deleted["sessionId"] == "runtime:python"


def test_runtime_http_transport_uses_runtime_routes(monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "TerraFinAgentService", lambda: _FakeService())
    request_log: list[tuple[str, str, dict | None]] = []

    def _fake_get(url: str, params: dict | None = None, timeout: float = 0):
        _ = timeout
        request_log.append(("GET", url, params))
        return _FakeResponse(200, {"ok": True, "path": url, "params": params})

    def _fake_post(url: str, json: dict | None = None, timeout: float = 0, headers: dict | None = None):
        _ = timeout, headers
        request_log.append(("POST", url, json))
        return _FakeResponse(200, {"ok": True, "path": url, "json": json})

    def _fake_delete(url: str, timeout: float = 0):
        _ = timeout
        request_log.append(("DELETE", url, None))
        return _FakeResponse(200, {"ok": True, "path": url})

    monkeypatch.setattr(agent_client.requests, "get", _fake_get)
    monkeypatch.setattr(agent_client.requests, "post", _fake_post)
    monkeypatch.setattr(agent_client.requests, "delete", _fake_delete)
    client = agent_client.TerraFinAgentClient(transport="http", base_url="http://127.0.0.1:8001")

    catalog = client.runtime_agents()
    session = client.runtime_create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="runtime:http")
    sessions = client.runtime_sessions()
    current = client.runtime_session("runtime:http")
    run = client.runtime_message("runtime:http", "Give me AAPL.")
    deleted = client.runtime_delete_session("runtime:http")

    assert request_log == [
        ("GET", "http://127.0.0.1:8001/agent/api/runtime/agents", None),
        (
            "POST",
            "http://127.0.0.1:8001/agent/api/runtime/sessions",
            {
                "agentName": DEFAULT_HOSTED_AGENT_NAME,
                "sessionId": "runtime:http",
                "systemPrompt": None,
                "metadata": {},
            },
        ),
        ("GET", "http://127.0.0.1:8001/agent/api/runtime/sessions", None),
        ("GET", "http://127.0.0.1:8001/agent/api/runtime/sessions/runtime:http", None),
        (
            "POST",
            "http://127.0.0.1:8001/agent/api/runtime/sessions/runtime:http/messages",
            {"content": "Give me AAPL."},
        ),
        ("DELETE", "http://127.0.0.1:8001/agent/api/runtime/sessions/runtime:http", None),
    ]
    assert catalog["ok"] is True
    assert session["ok"] is True
    assert sessions["ok"] is True
    assert current["ok"] is True
    assert run["ok"] is True
    assert deleted["ok"] is True
