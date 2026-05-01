"""HTTP implementation of AlertProvider.

Env vars:
  TERRAFIN_SIGNALS_PROVIDER_URL   — base URL of external alert API (required)
  TERRAFIN_SIGNALS_PROVIDER_KEY   — Bearer token for the external API
  (legacy ``TERRAFIN_ALERT_PROVIDER_*`` still honored with a deprecation log)
"""
import logging

from TerraFin.signals.env import signals_env

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

    async def list_subscribed(self) -> list[str]:
        """Return tickers currently subscribed on the provider, aggregated
        across all brokers. Used to detect orphans (subscribed but not in
        the watchlist monitor set)."""
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx required: pip install httpx") from exc
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/health", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        out: list[str] = []
        for broker in (data.get("brokers") or {}).values():
            out.extend(broker.get("subscribed") or [])
        return out

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
    url = signals_env("TERRAFIN_SIGNALS_PROVIDER_URL", "TERRAFIN_ALERT_PROVIDER_URL")
    if not url:
        return None
    key = signals_env("TERRAFIN_SIGNALS_PROVIDER_KEY", "TERRAFIN_ALERT_PROVIDER_KEY")
    return HttpAlertProvider(base_url=url, api_key=key)


def is_alert_provider_configured() -> bool:
    """True iff the env carries a provider URL — used by the watchlist UI to
    decide whether to surface the per-row monitor toggle."""
    return bool(signals_env("TERRAFIN_SIGNALS_PROVIDER_URL", "TERRAFIN_ALERT_PROVIDER_URL"))
