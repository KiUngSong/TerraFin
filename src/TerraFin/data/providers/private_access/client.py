from urllib.parse import urljoin

import requests

from TerraFin.data.providers.private_access.config import PrivateAccessConfig


class PrivateAccessClient:
    def __init__(self, config: PrivateAccessConfig) -> None:
        self.config = config

    def fetch_panel(self, resource: str) -> dict:
        """Fetch a non-time-series panel payload (raw JSON dict)."""
        return self._request_resource(resource)

    def fetch_series_history(self, series_key: str) -> list[dict]:
        """Fetch canonical {time, close} chart-series history from the data backend."""
        payload = self._request_resource(f"series/{series_key}")
        return list(payload.get("records", []))

    def fetch_series_current(self, series_key: str) -> dict:
        """Fetch IndicatorSnapshot wire payload for a series' most recent value."""
        return self._request_resource(f"series/{series_key}/current")

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
