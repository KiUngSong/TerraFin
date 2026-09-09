"""Breakout / range conditions — 52-week new high/low, weekly volume dry-up,
and the VCP base detector (Minervini)."""

from ._base import (
    Signal,
    sma,
    swing_pivots,
    venue_trend_ok,
    week_ending,
    weekly_bars,
)
from ._base import (
    closes as _closes,
)
from ._base import (
    volumes as _volumes,
)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_fifty_two_week_new_high(ticker, ohlc))
    out.extend(_fifty_two_week_new_low(ticker, ohlc))
    out.extend(_weekly_volume_dryup_signal(ticker, ohlc))
    out.extend(_weekly_new_extreme(ticker, ohlc))
    return out


# ─── 52-week new high / low (anchor effect; George/Hwang 2004) ───────────────


def fifty_two_week_high_status(ohlc, *, proximity: float = 0.98) -> dict | None:
    """Pure 52-week-high facts — NO regime gate, NO Signal wrapping.

    Shared math core (single source of truth) behind both the gated
    `_fifty_two_week_new_high` monitoring signal and callers that want raw
    facts for any region/instrument (KR names, ETFs). The gated signal keys on
    the trend of the index the name trades under, so it carries a regime
    opinion this one deliberately does not.

    Returns None when fewer than 252 daily bars exist, so a "52-week" stat is
    never computed off a short window (e.g. a recently-listed ETF). Otherwise:
      high_252           trailing-252 max close
      ratio              close / high_252  (1.0 at the high)
      pct_from_high      ratio - 1.0       (0.0 at the high, negative below)
      new_high           close >= high_252 and the prior bar was below it
      above_50dma        close > 50-day SMA
      entered_proximity  first bar to cross into the >= `proximity` zone
    """
    cs = _closes(ohlc)
    if len(cs) < 252:
        return None
    high_252 = max(cs[-252:])
    if high_252 <= 0:
        return None
    sma50 = sum(cs[-50:]) / 50
    ratio = cs[-1] / high_252
    new_high = cs[-1] >= high_252 and cs[-2] < high_252
    prev_high = max(cs[-253:-1]) if len(cs) >= 253 else high_252
    prev_ratio = (cs[-2] / prev_high) if prev_high > 0 else None
    entered_proximity = ratio >= proximity and prev_ratio is not None and prev_ratio < proximity
    return {
        "high_252": high_252,
        "ratio": ratio,
        "pct_from_high": ratio - 1.0,
        "new_high": bool(new_high),
        "above_50dma": cs[-1] > sma50,
        "sma50": sma50,
        "entered_proximity": bool(entered_proximity),
    }


def _fifty_two_week_new_high(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 252 + 51:
        return []
    st = fifty_two_week_high_status(ohlc)
    if st is None:
        return []
    high_252 = st["high_252"]
    sma50 = st["sma50"]
    if st["new_high"] and st["above_50dma"]:
        # Regime gate — bear-period backtest showed 52W_NEW_HIGH at
        # -7.27% (GFC) and -8.18% (COVID) edge; counter-trend pops chase
        # the high then die. Suppress when the name's own market isn't
        # trending up: KOSPI or KOSDAQ for a KRX name, SPY otherwise. An
        # unavailable index reads unknown and never suppresses.
        if venue_trend_ok(ticker, 50) is False:
            return []
        return [
            Signal(
                name="52W_NEW_HIGH",
                ticker=ticker,
                severity="high",
                message=(
                    f"New 52-week high (close {cs[-1]:.2f} ≥ {high_252:.2f}, "
                    f"above 50DMA {sma50:.2f}). Anchor-effect setup."
                ),
                snapshot={"close": cs[-1], "high_252": high_252, "sma50": sma50},
            )
        ]
    return []


def _fifty_two_week_new_low(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 252 + 51:
        return []
    low_252 = min(cs[-252:])
    sma50 = sum(cs[-50:]) / 50
    new_low = cs[-1] <= low_252 and cs[-2] > low_252
    if new_low and cs[-1] < sma50:
        return [
            Signal(
                name="52W_NEW_LOW",
                ticker=ticker,
                severity="high",
                message=(f"New 52-week low (close {cs[-1]:.2f} ≤ {low_252:.2f}, below 50DMA {sma50:.2f})."),
                snapshot={"close": cs[-1], "low_252": low_252, "sma50": sma50},
            )
        ]
    return []


# ─── VCP (Volatility Contraction Pattern) ────────────────────────────────────
#
# Minervini's VCP: a base of SUCCESSIVE, progressively SHALLOWER pullbacks
# (T1 > T2 > T3 …, typically 2-6 "footprints") with volume drying up into the
# right side, setting up a pivot whose breakout occurs on volume expansion.
# VCP is fuzzy by nature — this is a heuristic detector, not a precise oracle.
# It's the ENTRY-timing layer of SEPA (the Trend Template + RS is the screen).


def detect_vcp(
    ohlc,
    *,
    window: int = 130,
    half: int = 3,
    min_contractions: int = 2,
    max_contractions: int = 6,
    max_latest_depth: float = 0.12,
) -> dict | None:
    """Heuristic VCP base detection over the last `window` daily bars.

    Returns a dict (n_contractions, depths newest-last, pivot, volume_drying,
    breakout) when a contracting base is present, else None. Logic:
      - swing pivots on closes → successive high→low pullback depths
      - require >=min_contractions, each shallower than the prior (contracting)
      - latest contraction tight (<= max_latest_depth)
      - volume drying up: recent third's avg volume < first third's
      - pivot = most recent swing high; breakout = close >= pivot
    """
    cs = _closes(ohlc)
    vs = _volumes(ohlc)
    if vs is None or len(cs) < window or len(vs) < window:
        return None
    cs_w, vs_w = cs[-window:], vs[-window:]
    piv = swing_pivots(cs_w, half=half)
    if len(piv) < 3:
        return None
    depths: list[float] = []
    for a, b in zip(piv, piv[1:]):
        if a.side == 1 and b.side == -1 and a.price > 0:
            depths.append((a.price - b.price) / a.price)
    if len(depths) < min_contractions:
        return None
    depths = depths[-max_contractions:]
    contracting = all(depths[i] < depths[i - 1] for i in range(1, len(depths)))
    if not (contracting and depths[-1] <= max_latest_depth):
        return None
    third = max(1, window // 3)
    volume_drying = (sum(vs_w[-third:]) / third) < (sum(vs_w[:third]) / third)
    last_high = max((p.price for p in piv if p.side == 1), default=None)
    breakout = last_high is not None and cs_w[-1] >= last_high
    return {
        "n_contractions": len(depths),
        "depths": [round(d, 3) for d in depths],
        "pivot": last_high,
        "volume_drying": volume_drying,
        "breakout": breakout,
    }


def detect_weekly_volume_dryup(
    ohlc,
    *,
    ticker: str = "",
    recent_weeks: int = 4,
    base_weeks: int = 12,
    ratio: float = 0.6,
) -> dict | None:
    """Weekly-bar volume dry-up inside a constructive (uptrend) context.

    Resamples to weekly (W-FRI) bars and flags supply drying up — the last
    `recent_weeks` average volume <= `ratio` x the prior `base_weeks` average —
    but ONLY when the name is in an uptrend and not breaking down. That trend
    gate is what makes the tag meaningful: volume dry-up in a maturing base is
    accumulation (Minervini), while the same dry-up in a downtrend is just a
    name nobody wants to own. Without the gate the signal's SIGN is ambiguous,
    so this never reports a bare "volume dried up".

    Gate: latest weekly close above a RISING 30-week SMA, and the close sitting
    in the upper part of its recent weekly range (>= 40th percentile) so a name
    making fresh lows on light volume is excluded.

    Returns the metrics dict when the constructive dry-up holds, else None.
    """
    try:
        weekly = weekly_bars(ohlc, ticker)
    except Exception:
        return None
    cs = _closes(weekly)
    vs = _volumes(weekly)
    need = recent_weeks + base_weeks
    if vs is None or len(cs) < max(need, 31) or len(vs) < need:
        return None
    recent_avg = sum(vs[-recent_weeks:]) / recent_weeks
    base_avg = sum(vs[-need:-recent_weeks]) / base_weeks
    if base_avg <= 0:
        return None
    vol_ratio = recent_avg / base_avg
    if vol_ratio > ratio:
        return None
    # Trend gate — above a rising 30-week SMA, not making fresh lows.
    sma30 = sma(cs, 30)
    if len(sma30) < 2:
        return None
    rising = sma30[-1] > sma30[-2]
    above = cs[-1] > sma30[-1]
    win = cs[-need:]
    lo, hi = min(win), max(win)
    pos = (cs[-1] - lo) / (hi - lo) if hi > lo else 1.0
    if not (rising and above and pos >= 0.4):
        return None
    return {
        "dryup": True,
        "recent_avg": recent_avg,
        "base_avg": base_avg,
        "ratio": round(vol_ratio, 3),
        "recent_weeks": recent_weeks,
        "base_weeks": base_weeks,
        "week_ending": week_ending(weekly),
    }


def _weekly_volume_dryup_signal(ticker: str, ohlc) -> list[Signal]:
    d = detect_weekly_volume_dryup(ohlc, ticker=ticker)
    if d is None:
        return []
    return [
        Signal(
            name="WEEKLY_VOLUME_DRYUP",
            ticker=ticker,
            severity="medium",
            message=(
                f"Weekly volume dried up to {d['ratio']:.0%} of the prior "
                f"{d['base_weeks']}-week average while holding an uptrend — "
                f"supply contraction in a maturing base."
            ),
            snapshot={
                "ratio": d["ratio"],
                "recent_avg": d["recent_avg"],
                "base_avg": d["base_avg"],
                "week_ending": d.get("week_ending"),
            },
        )
    ]


# ─── Weekly 52-week new high / low ───────────────────────────────────────────


def _weekly_new_extreme(ticker: str, ohlc, *, lookback: int = 52, trend_sma: int = 10) -> list[Signal]:
    """52-week extreme confirmed by a WEEKLY close, not an intraweek touch.

    Same anchor effect as the daily pair, but a week has to close at the
    extreme, so intraweek spikes that reverse by Friday never fire. That is
    what makes it worth pushing for names the user has not curated.
    """
    try:
        weekly = weekly_bars(ohlc, ticker)
    except Exception:
        return []
    cs = _closes(weekly)
    if len(cs) < lookback + trend_sma + 1:
        return []
    trend = sum(cs[-trend_sma:]) / trend_sma
    window = cs[-lookback:]
    high, low = max(window), min(window)

    # `cs[-2] < high` against the SAME window is the daily signal's `new_high`
    # test (`fifty_two_week_high_status`). Comparing cs[-2] to its own trailing
    # window instead reads as "cs[-2] was not its own max", which is false
    # throughout any steady advance — the detector then never fires on the case
    # it exists for. The comparison must stay STRICT: `<=` would re-fire every
    # week a flat close ties the 52-week max.
    #
    # The trend test below is implied by the extreme test — a close that is the
    # max of the last 52 weeks is necessarily at or above the mean of the last
    # 10 — and is kept only so the emitted message's "above the N-week MA"
    # claim is explicit rather than inferred.
    if cs[-1] >= high and cs[-2] < high and cs[-1] > trend:
        # Regime gate on the name's own market, as the daily signal uses.
        # Gating a KRX name on a US index measures the wrong market; leaving
        # it ungated is the configuration the bear-period backtest condemned.
        if venue_trend_ok(ticker, 50) is False:
            return []
        return [
            Signal(
                name="WEEKLY_NEW_HIGH",
                ticker=ticker,
                severity="high",
                message=(
                    f"Weekly close at a {lookback}-week high "
                    f"({cs[-1]:.2f} ≥ {high:.2f}, above the {trend_sma}-week MA {trend:.2f})."
                ),
                snapshot={
                    "close": cs[-1],
                    "high": high,
                    "trend_sma": trend,
                    "lookback": lookback,
                    "week_ending": week_ending(weekly),
                },
            )
        ]
    if cs[-1] <= low and cs[-2] > low and cs[-1] < trend:
        return [
            Signal(
                name="WEEKLY_NEW_LOW",
                ticker=ticker,
                severity="high",
                message=(
                    f"Weekly close at a {lookback}-week low "
                    f"({cs[-1]:.2f} ≤ {low:.2f}, below the {trend_sma}-week MA {trend:.2f})."
                ),
                snapshot={
                    "close": cs[-1],
                    "low": low,
                    "trend_sma": trend,
                    "lookback": lookback,
                    "week_ending": week_ending(weekly),
                },
            )
        ]
    return []
