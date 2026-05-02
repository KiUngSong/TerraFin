"""Reversal conditions — engulfing, Sperandeo 1-2-3, RSI/price divergence."""

from ._base import (
    Signal,
    swing_pivots,
    wilder_rsi,
)
from ._base import (
    closes as _closes,
)
from ._base import (
    highs as _highs,
)
from ._base import (
    lows as _lows,
)
from ._base import (
    opens as _opens,
)
from ._base import (
    volumes as _volumes,
)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_engulfing(ticker, ohlc))
    out.extend(_rsi_divergence(ticker, ohlc))
    return out


# ─── Engulfing reversal at extreme location + volume confirm ─────────────────


def _engulfing(
    ticker: str,
    ohlc,
    *,
    location_window: int = 10,
    vol_multiple: float = 1.5,
) -> list[Signal]:
    cs = _closes(ohlc)
    os = _opens(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if len(cs) < max(location_window, 21):
        return []
    if len(os) != len(cs):
        return []
    prev_c, prev_o = cs[-2], os[-2]
    cur_c, cur_o = cs[-1], os[-1]

    if vs is not None and len(vs) >= 21:
        avg_vol = sum(vs[-21:-1]) / 20
        if avg_vol > 0 and vs[-1] < avg_vol * vol_multiple:
            return []
        vol_ratio = (vs[-1] / avg_vol) if avg_vol > 0 else None
    else:
        vol_ratio = None

    prior_lows = ls[-(location_window + 1) : -1]
    prior_highs = hs[-(location_window + 1) : -1]

    bullish = (
        prev_c < prev_o
        and cur_c > cur_o
        and cur_o <= prev_c
        and cur_c >= prev_o
        and prior_lows
        and ls[-1] <= min(prior_lows)
    )
    if bullish:
        msg = f"Bullish engulfing at {location_window}-bar low (close {cur_c:.2f}"
        if vol_ratio:
            msg += f", vol×{vol_ratio:.1f}"
        msg += ")."
        return [
            Signal(
                name="ENGULFING_BULL",
                ticker=ticker,
                severity="medium",
                message=msg,
                snapshot={"close": cur_c, "vol_ratio": vol_ratio},
            )
        ]
    bearish = (
        prev_c > prev_o
        and cur_c < cur_o
        and cur_o >= prev_c
        and cur_c <= prev_o
        and prior_highs
        and hs[-1] >= max(prior_highs)
    )
    if bearish:
        msg = f"Bearish engulfing at {location_window}-bar high (close {cur_c:.2f}"
        if vol_ratio:
            msg += f", vol×{vol_ratio:.1f}"
        msg += ")."
        return [
            Signal(
                name="ENGULFING_BEAR",
                ticker=ticker,
                severity="medium",
                message=msg,
                snapshot={"close": cur_c, "vol_ratio": vol_ratio},
            )
        ]
    return []


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
