"""Trend conditions — moving-average crosses, Minervini template."""

from ._base import Signal, resample, sma, spy_trend_ok
from ._base import closes as _closes


# Close-vs-MA(N) golden/death crosses, evaluated on a grid of MA lengths and
# timeframes. Daily uses the raw frame; weekly resamples first.
_DAILY_MA_PERIODS = (20, 60, 120, 200)
_WEEKLY_MA_PERIODS = (20, 60, 120)


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_ma_cross_grid(ticker, ohlc))
    out.extend(_minervini_template(ticker, ohlc))
    return out


# ─── Close-vs-MA(N) cross grid (daily + weekly) ──────────────────────────────


def _ma_cross_grid(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    for p in _DAILY_MA_PERIODS:
        out.extend(_bar_ma_cross(ticker, ohlc, period=p, label=f"MA{p}", horizon="day"))
    try:
        weekly = resample(ohlc, "W")
    except ValueError:
        return out
    for p in _WEEKLY_MA_PERIODS:
        out.extend(_bar_ma_cross(ticker, weekly, period=p, label=f"MA{p}W", horizon="week"))
    return out


def _side(close: float, ma: float, min_gap: float) -> int:
    if ma <= 0:
        return 0
    gap = (close - ma) / ma
    if gap >= min_gap:
        return 1
    if gap <= -min_gap:
        return -1
    return 0


def _bar_ma_cross(
    ticker: str,
    ohlc,
    *,
    period: int,
    label: str,
    horizon: str,
    min_gap_pct: float = 0.5,
) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < period + 1:
        return []
    mas = sma(cs, period)
    if len(mas) < 2:
        return []
    min_gap = min_gap_pct / 100.0
    cur_side = _side(cs[-1], mas[-1], min_gap)
    prev_side = _side(cs[-2], mas[-2], min_gap)
    if cur_side == 0 or prev_side == 0 or cur_side == prev_side:
        return []
    kind = "golden" if cur_side == 1 else "death"
    gap_pct = (cs[-1] - mas[-1]) / mas[-1] * 100.0
    return [
        Signal(
            name=f"{label}_{'GOLDEN' if cur_side == 1 else 'DEATH'}_CROSS",
            ticker=ticker,
            severity="medium",
            message=(f"{period}-{horizon} MA {kind} cross (close {cs[-1]:.2f} vs MA {mas[-1]:.2f}, gap {gap_pct:+.2f}%)."),
            snapshot={"close": cs[-1], "ma": mas[-1], "gap_pct": gap_pct},
        )
    ]


# ─── Minervini Trend Template (entry only) ───────────────────────────────────


def _template_pass(cs: list[float]) -> bool | None:
    """Minervini Trend Template, criteria 1-7 (criterion 8, RS rank >= 70, is
    cross-sectional and applied by the universe-aware caller, not here).

    Faithful to "Trade Like a Stock Market Wizard": MA stacking 50>150>200,
    price above all three, 200-MA in a sustained (>=1mo, here also >=3mo) uptrend,
    >=30% above the 52w low, within 25% of the 52w high.
    """
    # need 263 closes for the 3-month-ago 200-MA slope reference
    if len(cs) < 263:
        return None
    c = cs[-1]
    sma50 = sum(cs[-50:]) / 50
    sma150 = sum(cs[-150:]) / 150
    sma200 = sum(cs[-200:]) / 200
    sma200_21_ago = sum(cs[-221:-21]) / 200    # 200-MA ~1 month ago
    sma200_63_ago = sum(cs[-263:-63]) / 200    # 200-MA ~3 months ago
    low_52w = min(cs[-252:])
    high_52w = max(cs[-252:])
    if low_52w <= 0:
        return None
    return (
        c > sma50                              # 5: price above 50-MA
        and c > sma150 and c > sma200          # 1: price above 150- AND 200-MA (explicit)
        and sma50 > sma150 > sma200            # 2+4: 50>150>200 MA stacking
        and sma200 > sma200_21_ago             # 3a: 200-MA rising over ~1 month
        and sma200_21_ago > sma200_63_ago      # 3b: sustained — rising the prior 2 months too
        and c >= low_52w * 1.30                # 6: >=30% above 52w low
        and c >= high_52w * 0.75               # 7: within 25% of 52w high
    )


def passes_trend_template(ohlc) -> bool:
    """True if the latest bar is IN the Minervini Trend Template (criteria 1-7).

    State check for screens — distinct from `_minervini_template` which fires
    only on the false→true transition. Criterion 8 (RS rating >= 70) is
    cross-sectional; apply it in the universe-aware caller. False on short data.
    """
    return _template_pass(_closes(ohlc)) is True


def _minervini_template(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 264:  # _template_pass needs 263; prev bar needs one more
        return []
    cur = _template_pass(cs)
    prev = _template_pass(cs[:-1])
    # Only fire on transition false → true (regime entry).
    if not (cur is True and prev is False):
        return []
    # Bullish-entry signals get a SPY regime gate. Bear-period backtest
    # (GFC, COVID, 2022) showed all three negative-edge for Minervini —
    # the template flips green in counter-trend rallies, then dies. Only
    # fire when the broad market is itself in primary uptrend.
    if spy_trend_ok(50) is False:
        return []
    return [
        Signal(
            name="MINERVINI_TEMPLATE",
            ticker=ticker,
            severity="high",
            message=(f"Minervini Trend Template entry (close {cs[-1]:.2f}; RS-vs-benchmark not yet implemented)."),
            snapshot={"close": cs[-1]},
        )
    ]
