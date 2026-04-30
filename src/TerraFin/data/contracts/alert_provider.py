"""Alert provider contract.

AlertProvider: protocol for registering tickers with an external real-time alert service.
InboundSignal: payload the external API POSTs back to TerraFin when a signal fires.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class AlertProvider(Protocol):
    async def register(self, tickers: list[str]) -> None: ...
    async def unregister(self, tickers: list[str]) -> None: ...


class InboundSignal(BaseModel):
    ticker: str
    signal: str  # human-readable, e.g. "20-day MA touch"
    severity: str | None = None
    signal_id: str | None = None  # sender-provided UUID; used for dedup
    fired_at: datetime | None = None
