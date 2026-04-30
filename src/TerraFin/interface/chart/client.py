import time
from urllib.parse import urlencode

import requests

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.interface.chart.formatters import build_source_payload
from TerraFin.interface.chart.routes import CHART_PATH
from TerraFin.interface.server import get_runtime_config, run_server, start_server


def _runtime_base_url() -> str:
    return get_runtime_config().base_url


def _runtime_url(path: str) -> str:
    runtime_config = get_runtime_config()
    prefix = runtime_config.base_path.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{runtime_config.base_url}{prefix}{normalized_path}"


def _runtime_chart_url(path: str, *, session_id: str | None = None) -> str:
    url = _runtime_url(path)
    if not session_id:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({'sessionId': session_id})}"


def _to_dataframe_list(
    data: TimeSeriesDataFrame | list[TimeSeriesDataFrame],
) -> list[TimeSeriesDataFrame]:
    if isinstance(data, TimeSeriesDataFrame):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, TimeSeriesDataFrame)]
    raise TypeError("Expected TimeSeriesDataFrame or list of TimeSeriesDataFrame.")


def _wait_for_server_ready(timeout_s: float = 10.0, poll_interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout_s
    ready_url = _runtime_url("/ready")
    timeout = max(1.0, poll_interval_s)
    while time.monotonic() < deadline:
        try:
            response = requests.get(ready_url, timeout=timeout)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("ready") is True or payload.get("status") == "ready":
                    return True
        except Exception:
            pass
        time.sleep(poll_interval_s)
    return False


def _ensure_server_ready() -> None:
    if _wait_for_server_ready(timeout_s=1.0, poll_interval_s=0.2):
        return
    try:
        start_server()
    except RuntimeError as exc:
        if "already in use" not in str(exc):
            raise
    if not _wait_for_server_ready(timeout_s=15.0, poll_interval_s=0.25):
        raise RuntimeError(f"Chart server did not become ready at {_runtime_base_url()}.")


def display_chart(df: TimeSeriesDataFrame | None) -> None:
    import socket

    runtime_config = get_runtime_config()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((runtime_config.host, runtime_config.port))
        sock.close()
    except OSError as e:
        if e.errno == 48 or "Address already in use" in str(e):
            print(f"Port {runtime_config.port} is already in use.")
            raise SystemExit(1) from e
        raise

    run_server(initial_data=df)


def display_chart_notebook(data: TimeSeriesDataFrame | list[TimeSeriesDataFrame]):
    from IPython.display import IFrame

    frames = _to_dataframe_list(data)
    session_id = "default"
    _ensure_server_ready()
    if frames:
        update_chart(frames if len(frames) > 1 else frames[0], session_id=session_id)
    return IFrame(src=_runtime_chart_url(CHART_PATH, session_id=session_id), width="80%", height=400)


def update_chart(
    data: TimeSeriesDataFrame | list[TimeSeriesDataFrame],
    pinned: bool = False,
    session_id: str | None = None,
) -> bool:
    frames = _to_dataframe_list(data)
    if not frames:
        return True
    payload = build_source_payload(frames)
    if pinned:
        payload["pinned"] = True
    try:
        _ensure_server_ready()
        r = requests.post(
            _runtime_url(f"{CHART_PATH}/api/chart-data"),
            json=payload,
            headers={"X-Session-ID": session_id} if session_id else None,
            timeout=20,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"update_chart failed (is the server running at {_runtime_base_url()}?): {e}")
        return False


def get_chart_selection() -> dict | None:
    try:
        r = requests.get(_runtime_url(f"{CHART_PATH}/api/chart-selection"), timeout=2)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


if __name__ == "__main__":
    from TerraFin.data import get_data_factory

    data_factory = get_data_factory()
    df = data_factory.get_market_data("S&P 500")
    update_chart(df)
