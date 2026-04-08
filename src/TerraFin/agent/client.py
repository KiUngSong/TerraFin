import uuid
from typing import Any, Iterable

import requests

from TerraFin.data.contracts import TimeSeriesDataFrame
from TerraFin.interface.chart import client as chart_client
from TerraFin.interface.chart.formatters import build_multi_payload

from .models import ChartOpenResponse
from .service import TerraFinAgentService


class TerraFinAgentClient:
    def __init__(
        self,
        *,
        transport: str = "auto",
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.transport = (transport or "auto").strip().lower()
        if self.transport not in {"auto", "python", "http"}:
            raise ValueError(f"Unsupported transport: {transport}")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout
        self._service = TerraFinAgentService()

    def _resolved_transport(self) -> str:
        if self.transport == "auto":
            return "http" if self.base_url else "python"
        return self.transport

    def _service_call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return getattr(self._service, method)(*args, **kwargs)

    def _http_url(self, path: str) -> str:
        if not self.base_url:
            raise ValueError("base_url is required for HTTP transport")
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"

    def _http_get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(self._http_url(path), params=params, timeout=self.timeout)
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = {}
            detail = payload.get("detail") or payload.get("error", {}).get("message") or f"HTTP {response.status_code}"
            raise RuntimeError(str(detail))
        return response.json()

    def resolve(self, query: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("resolve", query)
        return self._http_get("/agent/api/resolve", params={"q": query})

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("market_data", name, depth=depth, view=view)
        return self._http_get("/agent/api/market-data", params={"ticker": name, "depth": depth, "view": view})

    def indicators(self, name: str, indicators: str | Iterable[str], *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        indicator_text = indicators if isinstance(indicators, str) else ",".join(str(item) for item in indicators)
        if self._resolved_transport() == "python":
            return self._service_call("indicators", name, indicator_text, depth=depth, view=view)
        return self._http_get(
            "/agent/api/indicators",
            params={"ticker": name, "indicators": indicator_text, "depth": depth, "view": view},
        )

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("market_snapshot", name, depth=depth, view=view)
        return self._http_get("/agent/api/market-snapshot", params={"ticker": name, "depth": depth, "view": view})

    def economic(self, indicators: str | Iterable[str]) -> dict[str, Any]:
        indicator_text = indicators if isinstance(indicators, str) else ",".join(str(item) for item in indicators)
        if self._resolved_transport() == "python":
            return self._service_call("economic", indicator_text)
        return self._http_get("/agent/api/economic", params={"indicators": indicator_text})

    def portfolio(self, guru: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("portfolio", guru)
        return self._http_get("/agent/api/portfolio", params={"guru": guru})

    def company_info(self, ticker: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("company_info", ticker)
        return self._http_get("/agent/api/company", params={"ticker": ticker})

    def earnings(self, ticker: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("earnings", ticker)
        return self._http_get("/agent/api/earnings", params={"ticker": ticker})

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("financials", ticker, statement=statement, period=period)
        return self._http_get(
            "/agent/api/financials",
            params={"ticker": ticker, "statement": statement, "period": period},
        )

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("lppl_analysis", name, depth=depth, view=view)
        return self._http_get("/agent/api/lppl", params={"name": name, "depth": depth, "view": view})

    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("macro_focus", name, depth=depth, view=view)
        return self._http_get("/agent/api/macro-focus", params={"name": name, "depth": depth, "view": view})

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        category_text = None
        if isinstance(categories, str):
            category_text = categories
        elif categories is not None:
            category_text = ",".join(str(item) for item in categories)
        if self._resolved_transport() == "python":
            return self._service_call("calendar_events", year=year, month=month, categories=category_text, limit=limit)
        params: dict[str, Any] = {"year": year, "month": month}
        if category_text:
            params["categories"] = category_text
        if limit is not None:
            params["limit"] = limit
        return self._http_get("/agent/api/calendar", params=params)

    def open_chart(
        self,
        data_or_names: str | list[str] | TimeSeriesDataFrame | list[TimeSeriesDataFrame],
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or f"agent:{uuid.uuid4().hex}"
        if isinstance(data_or_names, TimeSeriesDataFrame):
            frames = [data_or_names]
            names = None
        elif isinstance(data_or_names, list) and data_or_names and all(
            isinstance(item, TimeSeriesDataFrame) for item in data_or_names
        ):
            frames = list(data_or_names)
            names = None
        elif isinstance(data_or_names, str):
            frames = None
            names = [data_or_names]
        elif isinstance(data_or_names, list) and all(isinstance(item, str) for item in data_or_names):
            frames = None
            names = [str(item) for item in data_or_names]
        else:
            raise TypeError("open_chart expects a name, list of names, TimeSeriesDataFrame, or list of TimeSeriesDataFrame")

        transport = self._resolved_transport()
        if transport == "python":
            return self._open_local_chart(frames=frames, names=names, session_id=sid)
        return self._open_remote_chart(frames=frames, names=names, session_id=sid)

    def _ensure_local_chart_server(self) -> None:
        chart_client._ensure_server_ready()

    def _open_local_chart(
        self,
        *,
        frames: list[TimeSeriesDataFrame] | None,
        names: list[str] | None,
        session_id: str,
    ) -> dict[str, Any]:
        self._ensure_local_chart_server()
        if frames is not None:
            if not chart_client.update_chart(frames if len(frames) > 1 else frames[0], session_id=session_id):
                raise RuntimeError("Failed to update the local TerraFin chart session.")
            chart_url = chart_client._runtime_chart_url("/chart", session_id=session_id)
            return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

        assert names is not None
        headers = {"X-Session-ID": session_id}
        first, *rest = names
        seed = requests.post(
            chart_client._runtime_url("/chart/api/chart-series/progressive/set"),
            json={"name": first, "pinned": True, "seedPeriod": "3y"},
            headers=headers,
            timeout=self.timeout,
        )
        if seed.status_code >= 400:
            raise RuntimeError(seed.json().get("error") or seed.json().get("detail") or "Failed to seed chart")
        for name in rest:
            response = requests.post(
                chart_client._runtime_url("/chart/api/chart-series/add"),
                json={"name": name},
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to add chart series")
        chart_url = chart_client._runtime_chart_url("/chart", session_id=session_id)
        return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

    def _open_remote_chart(
        self,
        *,
        frames: list[TimeSeriesDataFrame] | None,
        names: list[str] | None,
        session_id: str,
    ) -> dict[str, Any]:
        headers = {"X-Session-ID": session_id}
        if frames is not None:
            payload = build_multi_payload(frames)
            response = requests.post(
                self._http_url("/chart/api/chart-data"),
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to update chart")
            chart_url = f"{self.base_url}/chart?sessionId={session_id}"
            return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

        assert names is not None
        first, *rest = names
        seed = requests.post(
            self._http_url("/chart/api/chart-series/progressive/set"),
            json={"name": first, "pinned": True, "seedPeriod": "3y"},
            headers=headers,
            timeout=self.timeout,
        )
        if seed.status_code >= 400:
            raise RuntimeError(seed.json().get("error") or seed.json().get("detail") or "Failed to seed chart")
        for name in rest:
            response = requests.post(
                self._http_url("/chart/api/chart-series/add"),
                json={"name": name},
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to add chart series")
        chart_url = f"{self.base_url}/chart?sessionId={session_id}"
        return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()
