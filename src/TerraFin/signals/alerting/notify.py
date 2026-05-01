"""Channel adapter protocol + implementations.

Env vars:
  TERRAFIN_SIGNALS_CHANNEL=stdout        → print to terminal (default)
  TERRAFIN_SIGNALS_CHANNEL=file:<path>   → write JSON artifact
  TERRAFIN_SIGNALS_CHANNEL=webhook       → POST to external API
  TERRAFIN_WEBHOOK_URL                   → required when channel=webhook
  TERRAFIN_WEBHOOK_KEY                   → Bearer token for webhook

Legacy ``TERRAFIN_ALERT_CHANNEL`` is honored with a deprecation log.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class Channel(Protocol):
    def send(self, title: str, body_md: str, payload: dict) -> None:
        ...


class StdoutChannel:
    def send(self, title: str, body_md: str, payload: dict) -> None:
        print(f"=== {title} ===")
        print(body_md)


class FileArtifactChannel:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def send(self, title: str, body_md: str, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {"title": title, "body_md": body_md, "payload": payload}
        self.path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))


class WebhookChannel:
    """POST signals to an external API endpoint.

    The receiving server decides downstream routing (dashboard push, Telegram, etc.).
    Request body: {"title": str, "signals": list[dict]}
    Auth: Authorization: Bearer <key>
    """

    def __init__(self, url: str, api_key: str = "") -> None:
        self.url = url
        self.api_key = api_key

    def send(self, title: str, body_md: str, payload: dict) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for WebhookChannel: pip install httpx") from exc

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = httpx.post(
                self.url,
                json={"title": title, "signals": payload.get("signals", [])},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            log.error("Webhook delivery failed: %s", exc)
            raise


def get_channel_from_env() -> Channel:
    """Return the configured channel from environment variables."""
    from TerraFin.signals.env import signals_env

    channel_type = signals_env(
        "TERRAFIN_SIGNALS_CHANNEL", "TERRAFIN_ALERT_CHANNEL", default="stdout"
    )
    if channel_type.startswith("file:"):
        return FileArtifactChannel(channel_type.removeprefix("file:"))
    if channel_type == "webhook":
        url = os.environ.get("TERRAFIN_WEBHOOK_URL", "")
        if not url:
            raise RuntimeError(
                "TERRAFIN_WEBHOOK_URL must be set when TERRAFIN_SIGNALS_CHANNEL=webhook"
            )
        key = os.environ.get("TERRAFIN_WEBHOOK_KEY", "")
        return WebhookChannel(url, key)
    if channel_type == "telegram":
        from TerraFin.signals.channels.telegram import TelegramChannel
        return TelegramChannel.from_config()
    return StdoutChannel()
