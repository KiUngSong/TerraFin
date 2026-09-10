"""Mean-reversion conditions — RSI crossing into an extreme.

One rule: RSI(14) closing at or beyond 70 / 30 on a bar that was not there the
bar before. No pivots and no confirmation lag, so the signal lands on the bar
it describes rather than weeks later.
"""

from ._base import (
    Signal,
    bar_date,
    entered_extreme,
    week_ending,
    weekly_bars,
    wilder_rsi,
)
from ._base import (
    closes as _closes,
)


RSI_PERIOD = 14
OVERBOUGHT = 70.0
OVERSOLD = 30.0


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_rsi_extreme(ticker, ohlc))
    out.extend(_weekly_rsi_extreme(ticker, ohlc))
    return out


def _rsi_extreme(
    ticker: str,
    ohlc,
    *,
    name_prefix: str = "",
    severity: str = "medium",
    snapshot_extra: dict | None = None,
) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < RSI_PERIOD + 2:
        return []
    rsi = wilder_rsi(cs, n=RSI_PERIOD)
    if len(rsi) < 2:
        return []
    # lookback=1: the previous bar must have been outside the zone, so a name
    # parked above 70 for weeks fires once, on the crossing.
    if entered_extreme(rsi, threshold=OVERBOUGHT, low=False, lookback=1):
        name, direction, word = "RSI_OVERBOUGHT", "overbought", "above"
    elif entered_extreme(rsi, threshold=OVERSOLD, low=True, lookback=1):
        name, direction, word = "RSI_OVERSOLD", "oversold", "below"
    else:
        return []
    return [
        Signal(
            name=f"{name_prefix}{name}",
            ticker=ticker,
            severity=severity,
            message=(
                f"RSI({RSI_PERIOD}) crossed {word} "
                f"{OVERBOUGHT if direction == 'overbought' else OVERSOLD:.0f} "
                f"to {rsi[-1]:.1f} (close {cs[-1]:.2f})."
            ),
            snapshot={
                "rsi": rsi[-1],
                "rsi_prev": rsi[-2],
                "close": cs[-1],
                "trigger_bar": bar_date(ohlc, len(ohlc) - 1),
                **(snapshot_extra or {}),
            },
        )
    ]


def _weekly_rsi_extreme(ticker: str, ohlc) -> list[Signal]:
    """The same rule on weekly bars, at the same 70 / 30.

    Severity is `high`, as for every other weekly signal: a weekly RSI(14)
    reaches an extreme rarely enough to be worth pushing uncurated.
    """
    try:
        weekly = weekly_bars(ohlc, ticker)
    except Exception:
        return []
    return _rsi_extreme(
        ticker,
        weekly,
        name_prefix="WEEKLY_",
        severity="high",
        snapshot_extra={"week_ending": week_ending(weekly)},
    )
