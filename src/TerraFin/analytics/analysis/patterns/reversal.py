"""Reversal conditions — RSI/price divergence."""

from ._base import (
    Signal,
    swing_pivots,
    wilder_rsi,
)
from ._base import (
    closes as _closes,
)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_rsi_divergence(ticker, ohlc))
    return out


# ─── RSI / price divergence (fractal pivot based) ────────────────────────────


def _rsi_divergence(
    ticker: str,
    ohlc,
    *,
    rsi_period: int = 14,
    half_window: int = 3,
    rsi_high: float = 60.0,
    rsi_low: float = 40.0,
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
                        name="RSI_BEAR_DIVERGENCE",
                        ticker=ticker,
                        severity="medium",
                        message=(
                            f"RSI bearish divergence "
                            f"(price HH {p_highs[-1].price:.2f}, RSI lower-high "
                            f"{r_highs[-1].price:.1f})."
                        ),
                        snapshot={
                            "price_high": p_highs[-1].price,
                            "rsi_high": r_highs[-1].price,
                        },
                    )
                ]
    if len(p_lows) >= 2 and len(r_lows) >= 2 and last_idx - p_lows[-1].bar_index <= fire_window:
        if p_lows[-1].price < p_lows[-2].price and r_lows[-1].price > r_lows[-2].price:
            if r_lows[-2].price <= rsi_low:
                return [
                    Signal(
                        name="RSI_BULL_DIVERGENCE",
                        ticker=ticker,
                        severity="medium",
                        message=(
                            f"RSI bullish divergence "
                            f"(price LL {p_lows[-1].price:.2f}, RSI higher-low "
                            f"{r_lows[-1].price:.1f})."
                        ),
                        snapshot={
                            "price_low": p_lows[-1].price,
                            "rsi_low": r_lows[-1].price,
                        },
                    )
                ]
    return []
