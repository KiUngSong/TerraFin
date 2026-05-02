"""Named market patterns evaluated over OHLCV dataframes — a systematic,
rules-based pattern catalog.

Each pattern function checks "does this named market condition match on the
latest bar?" and returns zero or more ``Signal`` objects (ticker, name,
severity, message, snapshot). Patterns are stateless: same input → same
verdict.

## Pull vs push: same ``Signal``, different trigger

This package is the **pull-driven** side. Callers (the agent flow, weekly
reports, ad-hoc backtests) ask "evaluate every pattern on this frame now"
and get a list of matches.

The **push-driven** side lives at ``interface/monitor/``: an external
realtime monitor service holds a broker WebSocket open, runs its own
intraday detectors over the tick stream, and POSTs each fired event to
TerraFin. Both sides emit the same ``Signal`` dataclass — only how the
evaluation is triggered differs.

## Pattern schools

Split by methodology so a new pattern lands in an obvious file:

- ``trend``     — MA crosses, Minervini template, Faber TAA
- ``breakout``  — Bollinger / Donchian / squeeze / NR7 / Keltner / Wyckoff Spring
- ``meanrev``   — RSI extremes, Connors RSI(2)
- ``momentum``  — MACD cross, Coppock
- ``reversal``  — engulfing, RSI/price divergence
- ``volume``    — capitulation, OBV divergence, CMF, MFI

Each school module exposes ``evaluate(ticker, ohlc) -> list[Signal]``;
the package-level ``evaluate`` aggregates them.
"""

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from . import breakout, meanrev, momentum, reversal, trend, volume
from ._base import Severity, Signal


_ACTIVE_SCHOOLS = (trend, breakout, meanrev, momentum, reversal, volume)


def evaluate(ticker: str, ohlc: TimeSeriesDataFrame) -> list[Signal]:
    """Run every school's evaluator against the OHLC frame.

    The frame must follow the ``TimeSeriesDataFrame`` contract — lowercase
    ``time / open / high / low / close / volume`` columns. Volume is
    optional; volume-school patterns short-circuit when it is missing.
    """
    out: list[Signal] = []
    for school in _ACTIVE_SCHOOLS:
        out.extend(school.evaluate(ticker, ohlc))
    return out


__all__ = ["Signal", "Severity", "evaluate"]
