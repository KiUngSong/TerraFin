from urllib.parse import urljoin

import requests

from TerraFin.data.providers.private_access.config import PrivateAccessConfig
from TerraFin.data.providers.private_access.models import (
    CalendarResponse,
    MarketBreadthResponse,
    TopCompaniesResponse,
    TrailingForwardPeSpreadResponse,
    WatchlistSnapshotResponse,
)


class PrivateAccessClient:
    def __init__(self, config: PrivateAccessConfig) -> None:
        self.config = config

    def fetch_watchlist_snapshot(self) -> WatchlistSnapshotResponse:
        payload = self._request_resource("watchlist-snapshot")
        return WatchlistSnapshotResponse.model_validate(payload)

    def fetch_market_breadth(self) -> MarketBreadthResponse:
        payload = self._request_resource("market-breadth")
        return MarketBreadthResponse.model_validate(payload)

    def fetch_calendar_events(self) -> CalendarResponse:
        payload = self._request_resource("calendar-events")
        return CalendarResponse.model_validate(payload)

    def fetch_trailing_forward_pe_spread(self) -> TrailingForwardPeSpreadResponse:
        payload = self._request_resource("trailing-forward-pe-spread")
        return TrailingForwardPeSpreadResponse.model_validate(payload)

    def fetch_fear_greed(self) -> list[dict]:
        """Fetch full Fear & Greed history from DataFactory.

        Returns list of {"date": "YYYY-MM-DD", "score": int} dicts.
        """
        payload = self._request_resource("fear-greed")
        return payload.get("data", [])

    def fetch_series_history(self, series_key: str) -> list[dict]:
        """Fetch normalized chart-series history from DataFactory.

        Returns list of {"time": ..., "close": ...} dicts.
        """
        payload = self._request_resource(f"series/{series_key}")
        return payload.get("data", [])

    def fetch_fear_greed_current(self) -> dict:
        """Fetch real-time Fear & Greed score from DataFactory.

        Returns {"score": int, "rating": str, "timestamp": str,
        "previous_close": int, "previous_1_week": int, "previous_1_month": int}.
        """
        return self._request_resource("fear-greed/current")

    def fetch_cape_current(self) -> dict:
        """Fetch latest CAPE (Shiller PE10) from DataFactory.

        Returns {"date": "YYYY-MM", "cape": float}.
        """
        return self._request_resource("cape/current")

    def fetch_cape_history(self) -> list[dict]:
        """Fetch full CAPE history from DataFactory.

        Returns list of {"date": "YYYY-MM", "cape": float} dicts.
        """
        payload = self._request_resource("cape")
        return payload.get("data", [])

    def fetch_top_companies(self, top_k: int = 50) -> TopCompaniesResponse:
        """Fetch top companies by market cap from DataFactory.

        Returns list of {"rank", "ticker", "name", "marketCap", "country"} dicts.
        """
        payload = self._request_resource(f"top-companies?top_k={top_k}")
        return TopCompaniesResponse.model_validate(payload)

    def _request_resource(self, resource: str) -> dict:
        endpoint = self.config.endpoint
        if not endpoint:
            raise RuntimeError("Private access endpoint is not configured.")
        url = urljoin(endpoint.rstrip("/") + "/", resource)
        headers = {"Accept": "application/json"}
        if self.config.access_key and self.config.access_value:
            headers[self.config.access_key] = self.config.access_value
        try:
            response = requests.get(url, headers=headers, timeout=self.config.timeout_seconds)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 401:
                raise RuntimeError(
                    f"Private source authentication failed for resource '{resource}'. "
                    "Check TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE."
                ) from exc
            if status_code == 403:
                raise RuntimeError(
                    f"Private source access was denied for resource '{resource}'."
                ) from exc
            if status_code is not None:
                raise RuntimeError(
                    f"Private source request failed for resource '{resource}' with HTTP {status_code}."
                ) from exc
            raise RuntimeError(
                f"Private source request failed for resource '{resource}'."
            ) from exc
        except requests.Timeout as exc:
            raise RuntimeError(
                f"Private source request timed out for resource '{resource}'."
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Private source request failed for resource '{resource}'."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid payload for resource '{resource}'.")
        return payload
