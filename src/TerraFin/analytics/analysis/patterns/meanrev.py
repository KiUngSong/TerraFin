"""Mean-reversion conditions — RSI overbought/oversold + Connors RSI(2)."""

from TerraFin.analytics.analysis.technical.rsi import rsi

from ._base import Signal, sma, wilder_rsi
from ._base import closes as _closes


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_rsi_extremes(ticker, ohlc))
    out.extend(_connors_rsi2(ticker, ohlc))
    return out


# ─── Wilder RSI overbought / oversold ────────────────────────────────────────


def _rsi_extremes(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 30:
        return []
    _, values = rsi(cs)
    if not values:
        return []
    latest = values[-1]
    snapshot = {"rsi": round(latest, 2)}
    if latest >= 70:
        return [
            Signal(
                name="RSI_OVERBOUGHT",
                ticker=ticker,
                severity="high",
                message=f"RSI {latest:.1f} — overbought territory (≥70).",
                snapshot=snapshot,
            )
        ]
    if latest <= 30:
        return [
            Signal(
                name="RSI_OVERSOLD",
                ticker=ticker,
                severity="high",
                message=f"RSI {latest:.1f} — oversold territory (≤30).",
                snapshot=snapshot,
            )
        ]
    return []


# ─── Connors RSI(2) — uptrend dip entry ──────────────────────────────────────


def _connors_rsi2(
    ticker: str,
    ohlc,
    *,
    rsi_threshold: float = 10.0,
    sma_period: int = 200,
) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < sma_period + 3:
        return []
    rsi_series = wilder_rsi(cs, n=2)
    if len(rsi_series) < 2:
        return []
    cur_rsi, prev_rsi = rsi_series[-1], rsi_series[-2]
    sma_window = cs[-sma_period:]
    sma200 = sum(sma_window) / sma_period
    in_uptrend = cs[-1] > sma200
    is_oversold = cur_rsi < rsi_threshold
    was_oversold = prev_rsi < rsi_threshold
    if not (in_uptrend and is_oversold and not was_oversold):
        return []
    return [
        Signal(
            name="CONNORS_RSI2_DIP",
            ticker=ticker,
            severity="medium",
            message=(
                f"Connors RSI(2)={cur_rsi:.1f} <{rsi_threshold:.0f} "
                f"in uptrend (close {cs[-1]:.2f} > 200MA {sma200:.2f})."
            ),
            snapshot={"rsi2": cur_rsi, "close": cs[-1], "sma200": sma200},
        )
    ]
