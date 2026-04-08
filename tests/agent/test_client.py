import pandas as pd

import TerraFin.agent.client as agent_client
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
