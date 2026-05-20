"""Signal provider contract.

SignalProvider: protocol for registering tickers with an external real-time signal-emitting service.
InboundSignal: payload the external API POSTs back to TerraFin when a signal fires.
"""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel


class SignalProvider(Protocol):
    async def register(self, tickers: list[str]) -> None: ...
    async def unregister(self, tickers: list[str]) -> None: ...


class InboundSignal(BaseModel):
    ticker: str
    signal: str  # human-readable, e.g. "20-day MA touch"
    severity: str | None = None
    signal_id: str | None = None  # sender-provided UUID; used for dedup
    fired_at: datetime | None = None
    name: str = ""  # company/indicator display name; enriched by receiver if blank
    # Set by the detector; drives ▲/▼/◆. Optional for back-compat with
    # senders predating the typed-direction contract — when missing, the
    # inbound handler logs a warning and falls back to "neutral".
    direction: Literal["bull", "bear", "neutral"] | None = None
    snapshot: dict = {}  # detector context at fire time (OHLCV, indicator values, etc.)
