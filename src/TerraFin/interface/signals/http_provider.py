"""HTTP implementation of AlertProvider.

Env vars:
  TERRAFIN_ALERT_PROVIDER_URL   — base URL of external alert API (required)
  TERRAFIN_ALERT_PROVIDER_KEY   — Bearer token for the external API
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class HttpAlertProvider:
    """Posts ticker registrations to an external real-time alert service."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def register(self, tickers: list[str]) -> None:
        await self._post("/register", {"tickers": tickers})

    async def unregister(self, tickers: list[str]) -> None:
        await self._post("/unregister", {"tickers": tickers})

    async def _post(self, path: str, body: dict) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx required: pip install httpx") from exc

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=body,
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()


def get_alert_provider_from_env() -> HttpAlertProvider | None:
    """Return configured provider, or None if not set."""
    url = os.environ.get("TERRAFIN_ALERT_PROVIDER_URL", "")
    if not url:
        return None
    key = os.environ.get("TERRAFIN_ALERT_PROVIDER_KEY", "")
    return HttpAlertProvider(base_url=url, api_key=key)
