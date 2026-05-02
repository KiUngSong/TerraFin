"""Breakout conditions — Bollinger, Donchian, squeeze, swing pivot, Darvas,
NR7/Inside Bar, Keltner channel, 52-week high proximity, Wyckoff Spring/Upthrust."""

from TerraFin.analytics.analysis.technical.bollinger import bollinger_bands

from ._base import (
    Signal,
    atr,
    ema,
    resample,
    sma,
    spy_trend_ok,
    swing_pivots,
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
    volumes as _volumes,
)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_bollinger_breakout(ticker, ohlc))
    out.extend(_donchian_breakout(ticker, ohlc, period=50, vol_multiple=1.5))
    out.extend(_donchian_breakout_weekly(ticker, ohlc, period=52))
    out.extend(_bb_squeeze_release(ticker, ohlc))
    out.extend(_swing_pivot_break(ticker, ohlc))
    out.extend(_darvas_box(ticker, ohlc))
    out.extend(_nr7_inside_bar(ticker, ohlc))
    out.extend(_keltner_breakout(ticker, ohlc))
    out.extend(_fifty_two_week_high_proximity(ticker, ohlc))
    out.extend(_wyckoff_spring_upthrust(ticker, ohlc))
    return out


# ─── Bollinger band breakout (close beyond band) ────────────────────────────


def _bollinger_breakout(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 30:
        return []
    _, upper, lower = bollinger_bands(cs)
    if not upper or not lower:
        return []
    last_close = cs[-1]
    last_upper = upper[-1]
    last_lower = lower[-1]
    snapshot = {
        "close": round(last_close, 4),
        "bb_upper": round(last_upper, 4),
        "bb_lower": round(last_lower, 4),
    }
    if last_close > last_upper:
        return [
            Signal(
                name="BB_BREAKOUT_UP",
                ticker=ticker,
                severity="low",
                message=f"Price {last_close:.2f} broke above Bollinger upper {last_upper:.2f}.",
                snapshot=snapshot,
            )
        ]
    if last_close < last_lower:
        return [
            Signal(
                name="BB_BREAKOUT_DOWN",
                ticker=ticker,
                severity="medium",
                message=f"Price {last_close:.2f} broke below Bollinger lower {last_lower:.2f}.",
                snapshot=snapshot,
            )
        ]
    return []


# ─── Donchian N-bar high/low breakout (Turtle-style) ─────────────────────────


def _donchian_breakout(
    ticker: str,
    ohlc,
    *,
    period: int = 50,
    vol_multiple: float = 1.5,
    label_suffix: str = "",
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if len(cs) < period + 1:
        return []
    prior_high = max(hs[-(period + 1) : -1])
    prior_low = min(ls[-(period + 1) : -1])
    side = 0
    if cs[-1] > prior_high:
        side = +1
    elif cs[-1] < prior_low:
        side = -1
    else:
        return []

    avg_vol = None
    if vs is not None and len(vs) >= period:
        avg_vol = sum(vs[-(period + 1) : -1]) / period
        if avg_vol > 0 and vs[-1] < avg_vol * vol_multiple:
            return []

    ref = prior_high if side == +1 else prior_low
    kind = "↑" if side == +1 else "↓"
    name = f"DONCHIAN{period}{label_suffix}_{'UP' if side == +1 else 'DOWN'}"
    msg = f"{period}-bar Donchian breakout {kind} (close {cs[-1]:.2f} vs ref {ref:.2f})"
    if avg_vol and avg_vol > 0 and vs is not None:
        msg += f", vol×{vs[-1] / avg_vol:.1f}"
    msg += "."
    return [
        Signal(
            name=name,
            ticker=ticker,
            severity="high",
            message=msg,
            snapshot={"period": period, "side": side, "close": cs[-1], "ref": ref},
        )
    ]


def _donchian_breakout_weekly(ticker: str, ohlc, *, period: int = 52) -> list[Signal]:
    try:
        weekly = resample(ohlc, "W-FRI")
    except ValueError:
        return []
    sigs = _donchian_breakout(
        ticker,
        weekly,
        period=period,
        vol_multiple=1.0,
        label_suffix="W",
    )
    # Tag as weekly in message.
    for s in sigs:
        s.message = "(weekly) " + s.message
    return sigs


# ─── Bollinger Squeeze → expansion ───────────────────────────────────────────


def _bb_squeeze_release(
    ticker: str,
    ohlc,
    *,
    period: int = 20,
    std_dev: float = 2.0,
    atr_mult: float = 1.5,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    if len(cs) < period + 2:
        return []
    atrs = atr(hs, ls, cs, n=period)
    if len(atrs) < 2:
        return []
    atr_offset = len(cs) - len(atrs)

    def _bb_kelt_widths(end_idx_in_cs: int) -> tuple[float, float, float] | None:
        if end_idx_in_cs - period + 1 < 0:
            return None
        window = cs[end_idx_in_cs - period + 1 : end_idx_in_cs + 1]
        if len(window) < period:
            return None
        mid = sum(window) / period
        var = sum((v - mid) ** 2 for v in window) / period
        sd = var**0.5
        bb_w = 2 * std_dev * sd
        atr_idx = end_idx_in_cs - atr_offset
        if atr_idx < 0 or atr_idx >= len(atrs):
            return None
        kelt_w = 2 * atr_mult * atrs[atr_idx]
        return mid, bb_w, kelt_w

    cur = _bb_kelt_widths(len(cs) - 1)
    prev = _bb_kelt_widths(len(cs) - 2)
    if cur is None or prev is None:
        return []
    cur_mid, cur_bb, cur_kelt = cur
    _, prev_bb, prev_kelt = prev
    was_squeezed = prev_bb < prev_kelt
    is_squeezed = cur_bb < cur_kelt
    if not was_squeezed or is_squeezed:
        return []
    side = +1 if cs[-1] > cur_mid else -1
    return [
        Signal(
            name="BB_SQUEEZE_RELEASE",
            ticker=ticker,
            severity="high",
            message=(f"BB squeeze release {'↑' if side == 1 else '↓'} (close {cs[-1]:.2f} vs mid {cur_mid:.2f})."),
            snapshot={
                "side": side,
                "close": cs[-1],
                "midline": cur_mid,
                "bb_width": cur_bb,
                "kelt_width": cur_kelt,
            },
        )
    ]


# ─── Swing pivot break (close beyond last confirmed pivot ± k·ATR) ───────────


def _swing_pivot_break(
    ticker: str,
    ohlc,
    *,
    half_window: int = 3,
    min_break_atr: float = 0.5,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    if len(cs) < half_window * 4:
        return []
    atrs = atr(hs, ls, cs, n=14)
    if not atrs:
        return []
    atr_now = atrs[-1]
    pivots_hi = swing_pivots(hs, half=half_window)
    pivots_lo = swing_pivots(ls, half=half_window)
    last_high = pivots_hi[-1] if pivots_hi else None
    last_low = pivots_lo[-1] if pivots_lo else None
    threshold = min_break_atr * atr_now
    last_idx = len(cs) - 1

    if last_high is not None and last_high.bar_index < last_idx and cs[-1] > last_high.price + threshold:
        # Edge-trigger: prev bar must NOT have already broken.
        if last_idx >= 1 and cs[-2] <= last_high.price + threshold:
            return [
                Signal(
                    name="SWING_HIGH_BREAK",
                    ticker=ticker,
                    severity="medium",
                    message=(
                        f"Swing high break (close {cs[-1]:.2f} > pivot {last_high.price:.2f} + {min_break_atr}×ATR)."
                    ),
                    snapshot={"close": cs[-1], "pivot": last_high.price, "atr": atr_now},
                )
            ]
    if last_low is not None and last_low.bar_index < last_idx and cs[-1] < last_low.price - threshold:
        if last_idx >= 1 and cs[-2] >= last_low.price - threshold:
            return [
                Signal(
                    name="SWING_LOW_BREAK",
                    ticker=ticker,
                    severity="medium",
                    message=(
                        f"Swing low break (close {cs[-1]:.2f} < pivot {last_low.price:.2f} - {min_break_atr}×ATR)."
                    ),
                    snapshot={"close": cs[-1], "pivot": last_low.price, "atr": atr_now},
                )
            ]
    return []


# ─── Darvas Box breakout ─────────────────────────────────────────────────────


def _darvas_box(
    ticker: str,
    ohlc,
    *,
    confirm_bars: int = 3,
    vol_multiple: float = 1.5,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if len(cs) < 252 + confirm_bars + 1:
        return []
    n = len(cs)
    last_idx = n - 1
    # Find a confirmed box top: the highest high in the trailing 252 bars
    # preceding ``last_idx - confirm_bars`` that has held for ``confirm_bars``
    # bars without being exceeded.
    for top_idx in range(last_idx - confirm_bars, last_idx - 252, -1):
        if top_idx < 252:
            break
        # Must be a 52-week new high at top_idx.
        prior_high = max(hs[top_idx - 252 : top_idx])
        if hs[top_idx] <= prior_high:
            continue
        # Must hold for ``confirm_bars`` bars after.
        post = hs[top_idx + 1 : top_idx + 1 + confirm_bars]
        if len(post) < confirm_bars or max(post, default=0) >= hs[top_idx]:
            continue
        top = hs[top_idx]
        # Trigger: latest close above top, and on the latest bar specifically
        # (not earlier — we want one fire on the breakout bar).
        if cs[-1] <= top:
            return []
        if cs[-2] > top:
            return []  # already broken on prior bar
        if vs is not None and len(vs) >= 50:
            avg_vol = sum(vs[-50:]) / 50
            if avg_vol > 0 and vs[-1] < avg_vol * vol_multiple:
                return []
        return [
            Signal(
                name="DARVAS_BOX_BREAKOUT",
                ticker=ticker,
                severity="high",
                message=f"Darvas box breakout (close {cs[-1]:.2f} > top {top:.2f}).",
                snapshot={"close": cs[-1], "top": top, "top_idx": top_idx},
            )
        ]
    return []


# ─── NR7 / Inside Bar — volatility-contraction precursor ────────────────────


def _nr7_inside_bar(ticker: str, ohlc) -> list[Signal]:
    """Crabel NR7 + Inside Bar setup (signals the *setup*, not the break).

    NR7: today's range is the narrowest of the last 7 bars.
    Inside Bar: today's high < prior high AND low > prior low.
    Often coincide and are highest-conviction when both true.
    """
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    if len(hs) < 8:
        return []
    ranges = [h - l for h, l in zip(hs, ls)]
    nr7 = ranges[-1] == min(ranges[-7:])
    inside = hs[-1] < hs[-2] and ls[-1] > ls[-2]
    if nr7 and inside:
        return [
            Signal(
                name="NR7_INSIDE_BAR",
                ticker=ticker,
                severity="medium",
                message=(
                    f"NR7 + Inside Bar (range {ranges[-1]:.2f} — narrowest of 7, "
                    f"contained within prior). Volatility contraction precursor."
                ),
                snapshot={"range": ranges[-1], "prior_range": ranges[-2]},
            )
        ]
    # Standalone NR7 was retired — backtest showed 5971 fires across 53
    # tickers / 5y with only +2.60% / 56% hit at 60d, well below the
    # signal-to-noise threshold for a standalone alert. The combined
    # NR7 + Inside Bar setup above kept the tighter, more decisive cases.
    return []


# ─── Keltner channel breakout (ATR-based, complements Bollinger) ─────────────


def _keltner_breakout(
    ticker: str,
    ohlc,
    *,
    period: int = 20,
    atr_mult: float = 2.0,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    if len(cs) < period + 2:
        return []
    emas = ema(cs, period)
    atrs = atr(hs, ls, cs, n=period)
    if len(emas) < 2 or len(atrs) < 2:
        return []
    # Align — both start at index period-1 (atr) / period-1 (ema after seed).
    ema_now = emas[-1]
    atr_now = atrs[-1]
    upper = ema_now + atr_mult * atr_now
    lower = ema_now - atr_mult * atr_now
    # Edge-trigger: prior bar's close was inside, current is outside.
    ema_prev = emas[-2]
    atr_prev = atrs[-2]
    upper_prev = ema_prev + atr_mult * atr_prev
    lower_prev = ema_prev - atr_mult * atr_prev
    if cs[-2] <= upper_prev and cs[-1] > upper:
        return [
            Signal(
                name="KELTNER_BREAKOUT_UP",
                ticker=ticker,
                severity="low",
                message=(f"Close {cs[-1]:.2f} broke above Keltner upper {upper:.2f} (EMA{period} + {atr_mult}·ATR)."),
                snapshot={"close": cs[-1], "upper": upper, "ema": ema_now, "atr": atr_now},
            )
        ]
    if cs[-2] >= lower_prev and cs[-1] < lower:
        return [
            Signal(
                name="KELTNER_BREAKOUT_DOWN",
                ticker=ticker,
                severity="medium",
                message=(f"Close {cs[-1]:.2f} broke below Keltner lower {lower:.2f} (EMA{period} - {atr_mult}·ATR)."),
                snapshot={"close": cs[-1], "lower": lower, "ema": ema_now, "atr": atr_now},
            )
        ]
    return []


# ─── 52-week high proximity (anchor effect; George/Hwang 2004) ───────────────


def _fifty_two_week_high_proximity(
    ticker: str,
    ohlc,
    *,
    proximity: float = 0.98,
) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 252 + 51:
        return []
    high_252 = max(cs[-252:])
    if high_252 <= 0:
        return []
    ratio = cs[-1] / high_252
    prev_ratio = cs[-2] / max(cs[-253:-1]) if len(cs) >= 253 else None
    sma50 = sum(cs[-50:]) / 50
    above_50dma = cs[-1] > sma50
    new_high = cs[-1] >= high_252 and cs[-2] < high_252
    if new_high and above_50dma:
        # SPY regime gate — bear-period backtest showed 52W_NEW_HIGH at
        # -7.27% (GFC) and -8.18% (COVID) edge; counter-trend pops chase
        # the high then die. Suppress when SPY itself isn't trending up.
        if spy_trend_ok(50) is False:
            return []
        return [
            Signal(
                name="52W_NEW_HIGH",
                ticker=ticker,
                severity="medium",
                message=(
                    f"New 52-week high (close {cs[-1]:.2f} ≥ {high_252:.2f}, "
                    f"above 50DMA {sma50:.2f}). Anchor-effect setup."
                ),
                snapshot={"close": cs[-1], "high_252": high_252, "sma50": sma50},
            )
        ]
    # First time entering proximity zone (≥ 0.98 of high).
    if ratio >= proximity and prev_ratio is not None and prev_ratio < proximity and above_50dma:
        return [
            Signal(
                name="52W_HIGH_PROXIMITY",
                ticker=ticker,
                severity="low",
                message=(
                    f"Within {(1 - proximity) * 100:.0f}% of 52-week high "
                    f"(close {cs[-1]:.2f}, high {high_252:.2f}). "
                    f"George/Hwang anchor."
                ),
                snapshot={"close": cs[-1], "high_252": high_252, "ratio": ratio},
            )
        ]
    return []


# ─── Wyckoff Spring / Upthrust — failed-break reversal ───────────────────────


def _wyckoff_spring_upthrust(
    ticker: str,
    ohlc,
    *,
    range_period: int = 50,
    vol_multiple: float = 1.5,
) -> list[Signal]:
    # 20-bar range was too short — bear-period backtest showed Spring
    # firing into still-falling tape (GFC -3.11% / COVID -1.28% edge).
    # 50-bar range filters out continuation breaks within the same
    # downtrend leg.
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if len(cs) < range_period + 2 or vs is None or len(vs) != len(cs):
        return []
    prior_low = min(ls[-(range_period + 1) : -1])
    prior_high = max(hs[-(range_period + 1) : -1])
    avg_vol = sum(vs[-(range_period + 1) : -1]) / range_period
    if avg_vol <= 0:
        return []
    pierced_low = ls[-1] < prior_low
    closed_back_inside_range = cs[-1] > prior_low
    pierced_high = hs[-1] > prior_high
    closed_back_inside_top = cs[-1] < prior_high
    vol_ok = vs[-1] >= avg_vol * vol_multiple

    if pierced_low and closed_back_inside_range and vol_ok:
        return [
            Signal(
                name="WYCKOFF_SPRING",
                ticker=ticker,
                severity="high",
                message=(
                    f"Wyckoff Spring — bar pierced {range_period}-bar low "
                    f"({ls[-1]:.2f} < {prior_low:.2f}) but closed back inside "
                    f"({cs[-1]:.2f}) on vol×{vs[-1] / avg_vol:.1f}."
                ),
                snapshot={
                    "low": ls[-1],
                    "prior_low": prior_low,
                    "close": cs[-1],
                    "vol_ratio": vs[-1] / avg_vol,
                },
            )
        ]
    if pierced_high and closed_back_inside_top and vol_ok:
        return [
            Signal(
                name="WYCKOFF_UPTHRUST",
                ticker=ticker,
                severity="high",
                message=(
                    f"Wyckoff Upthrust — bar pierced {range_period}-bar high "
                    f"({hs[-1]:.2f} > {prior_high:.2f}) but closed back inside "
                    f"({cs[-1]:.2f}) on vol×{vs[-1] / avg_vol:.1f}."
                ),
                snapshot={
                    "high": hs[-1],
                    "prior_high": prior_high,
                    "close": cs[-1],
                    "vol_ratio": vs[-1] / avg_vol,
                },
            )
        ]
    return []
