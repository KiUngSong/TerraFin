from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_text(url: str) -> str:
    with urlopen(url, timeout=2.0) as response:
        return response.read().decode("utf-8")


def _fetch_json(url: str) -> dict:
    return json.loads(_fetch_text(url))


def _wait_for_server(proc: subprocess.Popen, port: int, timeout_seconds: float = 20.0) -> tuple[dict, str]:
    health_url = f"http://127.0.0.1:{port}/health"
    dashboard_url = f"http://127.0.0.1:{port}/dashboard"
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise RuntimeError(f"Package smoke server exited early: {stderr.strip()}")
        try:
            return _fetch_json(health_url), _fetch_text(dashboard_url)
        except (TimeoutError, URLError, ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for package smoke server: {last_error}")


def main() -> int:
    import TerraFin
    from TerraFin.analytics.analysis.fundamental.dcf.inputs import load_sp500_defaults
    from TerraFin.data.providers.corporate.filings.sec_edgar.holdings import load_guru_cik_registry
    from TerraFin.data.providers.private_access.fallbacks import get_watchlist_fallback

    _require(bool(getattr(TerraFin, "__version__", "")), "Installed package did not expose TerraFin.__version__.")
    _require(bool(load_sp500_defaults()), "Packaged sp500_defaults.json did not load.")
    _require(bool(load_guru_cik_registry()), "Packaged guru_cik.json did not load.")
    _require(len(get_watchlist_fallback().items) > 0, "Packaged fallback fixtures did not load.")

    port = _pick_free_port()
    server_code = (
        "from TerraFin.interface.server import create_app\n"
        "import sys, uvicorn\n"
        "uvicorn.run(create_app(), host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", server_code, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        health, dashboard_html = _wait_for_server(proc, port)
        _require(health.get("status") == "ok", f"Unexpected /health payload: {health}")
        _require(health.get("service") == "terrafin-interface", f"Unexpected service name: {health}")
        _require("TerraFin" in dashboard_html, "Dashboard HTML did not include TerraFin branding.")
        _require('<div id="root"></div>' in dashboard_html, "Dashboard page did not serve the SPA shell.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)

    print("package smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
