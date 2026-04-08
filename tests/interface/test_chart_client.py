import sys
from types import ModuleType, SimpleNamespace

import pandas as pd

import TerraFin.interface.chart.client as chart_client
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return dict(self._payload)


def _set_runtime(monkeypatch, *, base_url: str = "http://127.0.0.1:8001", base_path: str = "/terra") -> None:
    monkeypatch.setattr(
        chart_client,
        "get_runtime_config",
        lambda: SimpleNamespace(base_url=base_url, base_path=base_path, host="127.0.0.1", port=8001),
    )


def test_runtime_url_includes_base_path(monkeypatch) -> None:
    _set_runtime(monkeypatch, base_path="/terrafin")

    assert chart_client._runtime_url("/chart") == "http://127.0.0.1:8001/terrafin/chart"
    assert chart_client._runtime_url("ready") == "http://127.0.0.1:8001/terrafin/ready"


def test_wait_for_server_ready_polls_ready_endpoint(monkeypatch) -> None:
    _set_runtime(monkeypatch)
    responses = iter(
        [
            _FakeResponse(503, {"ready": False}),
            RuntimeError("not ready yet"),
            _FakeResponse(200, {"status": "ready", "ready": True}),
        ]
    )
    request_urls: list[str] = []
    sleep_calls: list[float] = []
    monotonic_values = iter([0.0, 0.1, 0.2, 0.3, 0.4])

    def _fake_get(url: str, timeout: float):
        _ = timeout
        request_urls.append(url)
        next_value = next(responses)
        if isinstance(next_value, Exception):
            raise next_value
        return next_value

    monkeypatch.setattr(chart_client.requests, "get", _fake_get)
    monkeypatch.setattr(chart_client.time, "sleep", lambda delay: sleep_calls.append(delay))
    monkeypatch.setattr(chart_client.time, "monotonic", lambda: next(monotonic_values))

    assert chart_client._wait_for_server_ready(timeout_s=1.0, poll_interval_s=0.2) is True
    assert request_urls == [
        "http://127.0.0.1:8001/terra/ready",
        "http://127.0.0.1:8001/terra/ready",
        "http://127.0.0.1:8001/terra/ready",
    ]
    assert sleep_calls == [0.2, 0.2]


def test_display_chart_notebook_starts_server_and_updates_chart(monkeypatch) -> None:
    _set_runtime(monkeypatch)
    wait_calls: list[tuple[float, float]] = []
    start_calls: list[str] = []
    update_calls: list[tuple[TimeSeriesDataFrame | list[TimeSeriesDataFrame], bool, str | None]] = []

    readiness_states = iter([False, True])

    def _fake_wait(timeout_s: float = 10.0, poll_interval_s: float = 0.2) -> bool:
        wait_calls.append((timeout_s, poll_interval_s))
        return next(readiness_states)

    def _fake_start_server() -> int:
        start_calls.append("started")
        return 1234

    def _fake_update_chart(data, pinned: bool = False, session_id: str | None = None) -> bool:
        update_calls.append((data, pinned, session_id))
        return True

    fake_ipython = ModuleType("IPython")
    fake_display = ModuleType("IPython.display")

    class _FakeIFrame:
        def __init__(self, *, src: str, width: str, height: int) -> None:
            self.src = src
            self.width = width
            self.height = height

    fake_display.IFrame = _FakeIFrame
    fake_ipython.display = fake_display
    monkeypatch.setitem(sys.modules, "IPython", fake_ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", fake_display)

    monkeypatch.setattr(chart_client, "_wait_for_server_ready", _fake_wait)
    monkeypatch.setattr(chart_client, "start_server", _fake_start_server)
    monkeypatch.setattr(chart_client, "update_chart", _fake_update_chart)

    df = TimeSeriesDataFrame(pd.DataFrame({"time": ["2026-01-01"], "close": [100.0]}), name="S&P 500")
    frame = chart_client.display_chart_notebook(df)

    assert wait_calls == [(1.0, 0.2), (15.0, 0.25)]
    assert start_calls == ["started"]
    assert update_calls == [(df, False, "default")]
    assert frame.src == "http://127.0.0.1:8001/terra/chart?sessionId=default"
    assert frame.width == "80%"
    assert frame.height == 400


def test_update_chart_posts_to_prefixed_chart_data(monkeypatch) -> None:
    _set_runtime(monkeypatch, base_path="/prefixed")
    request_log: list[tuple[str, dict, dict | None, float]] = []

    def _fake_post(url: str, json: dict, headers: dict | None = None, timeout: float = 0):
        request_log.append((url, json, headers, timeout))
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(chart_client, "_wait_for_server_ready", lambda timeout_s=10.0, poll_interval_s=0.2: True)
    monkeypatch.setattr(chart_client.requests, "post", _fake_post)
    df = TimeSeriesDataFrame(pd.DataFrame({"time": ["2026-01-01", "2026-01-02"], "close": [100.0, 101.0]}))

    assert chart_client.update_chart(df, pinned=True) is True
    assert request_log[0][0] == "http://127.0.0.1:8001/prefixed/chart/api/chart-data"
    assert request_log[0][1]["pinned"] is True
    assert request_log[0][1]["mode"] == "multi"
    assert request_log[0][1]["series"][0]["seriesType"] == "line"
    assert request_log[0][2] is None
    assert request_log[0][3] == 20


def test_update_chart_can_target_explicit_session(monkeypatch) -> None:
    _set_runtime(monkeypatch)
    request_log: list[tuple[str, dict, dict | None, float]] = []

    def _fake_post(url: str, json: dict, headers: dict | None = None, timeout: float = 0):
        request_log.append((url, json, headers, timeout))
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(chart_client, "_wait_for_server_ready", lambda timeout_s=10.0, poll_interval_s=0.2: True)
    monkeypatch.setattr(chart_client.requests, "post", _fake_post)
    df = TimeSeriesDataFrame(pd.DataFrame({"time": ["2026-01-01"], "close": [100.0]}))

    assert chart_client.update_chart(df, session_id="notebook:test-session") is True
    assert request_log[0][2] == {"X-Session-ID": "notebook:test-session"}
    assert request_log[0][3] == 20


def test_update_chart_posts_raw_candlestick_source_for_ohlc_frames(monkeypatch) -> None:
    _set_runtime(monkeypatch)
    request_log: list[dict] = []

    def _fake_post(url: str, json: dict, headers: dict | None = None, timeout: float = 0):
        _ = url, headers, timeout
        request_log.append(json)
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(chart_client, "_wait_for_server_ready", lambda timeout_s=10.0, poll_interval_s=0.2: True)
    monkeypatch.setattr(chart_client.requests, "post", _fake_post)
    df = TimeSeriesDataFrame(
        pd.DataFrame(
            {
                "time": ["2026-01-01", "2026-01-02"],
                "open": [99.5, 100.5],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.0, 101.0],
            }
        )
    )
    df.name = "OHLC"

    assert chart_client.update_chart(df) is True
    assert request_log[0]["series"][0]["seriesType"] == "candlestick"
    assert "open" in request_log[0]["series"][0]["data"][0]
