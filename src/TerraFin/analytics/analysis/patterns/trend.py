"""Trend conditions — moving averages, Minervini template, Faber TAA."""

from TerraFin.analytics.analysis.technical.ma import moving_average

from ._base import Signal, resample, sma, spy_trend_ok
from ._base import closes as _closes


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_ma_50_200_cross(ticker, ohlc))
    out.extend(_bar_ma_cross(ticker, ohlc, period=50, min_gap_pct=0.5))
    out.extend(_minervini_template(ticker, ohlc))
    out.extend(_faber_monthly(ticker, ohlc, period=10))
    return out


# ─── 50/200 golden / death cross ─────────────────────────────────────────────


def _ma_50_200_cross(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 202:
        return []
    _, fast = moving_average(cs, 50)
    _, slow = moving_average(cs, 200)
    if len(fast) < 2 or len(slow) < 2:
        return []
    trim = len(fast) - len(slow)
    fast_aligned = fast[trim:]
    diffs = [f - s for f, s in zip(fast_aligned, slow)]
    snapshot = {"ma50": round(fast_aligned[-1], 4), "ma200": round(slow[-1], 4)}
    # Only fire on the most recent bar's transition.
    if diffs[-2] < 0 <= diffs[-1]:
        return [
            Signal(
                name="MA_GOLDEN_CROSS",
                ticker=ticker,
                severity="medium",
                message="50-day MA crossed above 200-day MA (golden cross).",
                snapshot=snapshot,
            )
        ]
    if diffs[-2] > 0 >= diffs[-1]:
        return [
            Signal(
                name="MA_DEATH_CROSS",
                ticker=ticker,
                severity="high",
                message="50-day MA crossed below 200-day MA (death cross).",
                snapshot=snapshot,
            )
        ]
    return []


# ─── Generic close-vs-MA(N) cross with min-gap whipsaw filter ────────────────


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
    period: int = 50,
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
            name=f"MA{period}_{'GOLDEN' if cur_side == 1 else 'DEATH'}_CROSS",
            ticker=ticker,
            severity="medium",
            message=(f"{period}-day MA {kind} cross (close {cs[-1]:.2f} vs MA {mas[-1]:.2f}, gap {gap_pct:+.2f}%)."),
            snapshot={"close": cs[-1], "ma": mas[-1], "gap_pct": gap_pct},
        )
    ]


# ─── Minervini Trend Template (entry only) ───────────────────────────────────


def _template_pass(cs: list[float]) -> bool | None:
    if len(cs) < 252:
        return None
    c = cs[-1]
    sma50 = sum(cs[-50:]) / 50
    sma150 = sum(cs[-150:]) / 150
    sma200 = sum(cs[-200:]) / 200
    if len(cs) < 221:
        return None
    sma200_21_ago = sum(cs[-221:-21]) / 200
    low_52w = min(cs[-252:])
    high_52w = max(cs[-252:])
    if low_52w <= 0:
        return None
    return (
        c > sma50
        and sma50 > sma150 > sma200
        and sma200 > sma200_21_ago
        and c >= low_52w * 1.30
        and c >= high_52w * 0.75
    )


def _minervini_template(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 253:
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


# ─── Faber 10-month MA cross (monthly resample) ──────────────────────────────


def _faber_monthly(ticker: str, ohlc, *, period: int = 10) -> list[Signal]:
    try:
        monthly = resample(ohlc, "ME")
    except ValueError:
        return []
    cs = _closes(monthly)
    if len(cs) < period + 1:
        return []
    mas = sma(cs, period)
    if len(mas) < 2:
        return []
    cur_above = cs[-1] > mas[-1]
    prev_above = cs[-2] > mas[-2]
    if cur_above == prev_above:
        return []
    kind = "ENTER" if cur_above else "EXIT"
    return [
        Signal(
            name=f"FABER_MA{period}_{'ENTRY' if cur_above else 'EXIT'}",
            ticker=ticker,
            severity="high",
            message=(f"Faber {period}-month MA cross — {kind} (monthly close {cs[-1]:.2f} vs MA {mas[-1]:.2f})."),
            snapshot={"close": cs[-1], "ma": mas[-1]},
        )
    ]
