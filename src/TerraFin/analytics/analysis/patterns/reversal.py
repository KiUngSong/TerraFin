"""Reversal conditions — RSI/price divergence."""

from ._base import (
    Signal,
    bar_date,
    swing_pivots,
    week_ending,
    weekly_bars,
    wilder_rsi,
)
from ._base import (
    closes as _closes,
)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_rsi_divergence(ticker, ohlc))
    out.extend(_weekly_rsi_divergence(ticker, ohlc))
    return out


# ─── RSI / price divergence (fractal pivot based) ────────────────────────────


def _rsi_divergence(
    ticker: str,
    ohlc,
    *,
    rsi_period: int = 14,
    half_window: int = 3,
    rsi_high: float = 70.0,
    rsi_low: float = 30.0,
    name_prefix: str = "",
    severity: str = "medium",
    snapshot_extra: dict | None = None,
) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < rsi_period + half_window * 4 + 5:
        return []
    rsi_series = wilder_rsi(cs, n=rsi_period)
    if len(rsi_series) < half_window * 4:
        return []
    # Align: RSI starts at index `rsi_period` in cs.
    rsi_offset = len(cs) - len(rsi_series)
    cs_aligned = cs[rsi_offset:]
    pp = swing_pivots(cs_aligned, half=half_window)
    rp = swing_pivots(rsi_series, half=half_window)
    p_highs = [p for p in pp if p.side == +1]
    p_lows = [p for p in pp if p.side == -1]
    r_highs = [p for p in rp if p.side == +1]
    r_lows = [p for p in rp if p.side == -1]

    last_idx = len(cs_aligned) - 1
    # Fire only if the most recent confirmed pivot is recent (within 2*half).
    fire_window = half_window + 2

    if len(p_highs) >= 2 and len(r_highs) >= 2 and last_idx - p_highs[-1].bar_index <= fire_window:
        if p_highs[-1].price > p_highs[-2].price and r_highs[-1].price < r_highs[-2].price:
            if r_highs[-2].price >= rsi_high:
                return [
                    Signal(
                        name=f"{name_prefix}RSI_BEAR_DIVERGENCE",
                        ticker=ticker,
                        severity=severity,
                        message=(
                            f"RSI bearish divergence "
                            f"(price HH {p_highs[-1].price:.2f}, RSI lower-high "
                            f"{r_highs[-1].price:.1f})."
                        ),
                        snapshot={
                            "price_high": p_highs[-1].price,
                            "rsi_high": r_highs[-1].price,
                            "trigger_bar": bar_date(ohlc, rsi_offset + p_highs[-1].bar_index),
                            **(snapshot_extra or {}),
                        },
                    )
                ]
    if len(p_lows) >= 2 and len(r_lows) >= 2 and last_idx - p_lows[-1].bar_index <= fire_window:
        if p_lows[-1].price < p_lows[-2].price and r_lows[-1].price > r_lows[-2].price:
            if r_lows[-2].price <= rsi_low:
                return [
                    Signal(
                        name=f"{name_prefix}RSI_BULL_DIVERGENCE",
                        ticker=ticker,
                        severity=severity,
                        message=(
                            f"RSI bullish divergence "
                            f"(price LL {p_lows[-1].price:.2f}, RSI higher-low "
                            f"{r_lows[-1].price:.1f})."
                        ),
                        snapshot={
                            "price_low": p_lows[-1].price,
                            "rsi_low": r_lows[-1].price,
                            "trigger_bar": bar_date(ohlc, rsi_offset + p_lows[-1].bar_index),
                            **(snapshot_extra or {}),
                        },
                    )
                ]
    return []


def _weekly_rsi_divergence(ticker: str, ohlc) -> list[Signal]:
    """Same divergence rule on weekly bars.

    Severity is `high`, not the daily `medium`: a divergence that takes months
    of weekly pivots to form is rare and is the class of signal worth pushing
    for a name the user has not curated.
    """
    try:
        weekly = weekly_bars(ohlc, ticker)
    except Exception:
        return []
    # Looser bounds than the daily 70/30: weekly RSI(14) rarely reaches either
    # extreme, and at 30 the bull side never fired on any name tested.
    # `week_ending` is what keys the weekly dedup. Without it these fall back to
    # the run date's ISO week, which double-ships on the KRX schedule and then
    # swallows the following week.
    return _rsi_divergence(
        ticker,
        weekly,
        rsi_high=60.0,
        rsi_low=40.0,
        name_prefix="WEEKLY_",
        severity="high",
        snapshot_extra={"week_ending": week_ending(weekly)},
    )
