"""Momentum conditions — MACD signal-line cross + Coppock buy."""

from TerraFin.analytics.analysis.technical.macd import macd

from ._base import Signal, ema, resample
from ._base import closes as _closes


def evaluate(ticker: str, ohlc) -> list[Signal]:
    out: list[Signal] = []
    out.extend(_macd_cross(ticker, ohlc))
    out.extend(_coppock_monthly(ticker, ohlc))
    return out


# ─── MACD signal-line cross ──────────────────────────────────────────────────


def _macd_cross(ticker: str, ohlc) -> list[Signal]:
    cs = _closes(ohlc)
    if len(cs) < 30:
        return []
    _, macd_line, signal_line, histogram = macd(cs)
    if len(histogram) < 2:
        return []
    snapshot = {
        "macd": round(macd_line[-1], 4) if macd_line else None,
        "signal": round(signal_line[-1], 4) if signal_line else None,
        "histogram": round(histogram[-1], 4),
    }
    # Most recent transition only — not "anywhere in history".
    if histogram[-2] < 0 <= histogram[-1]:
        return [
            Signal(
                name="MACD_BULL_CROSS",
                ticker=ticker,
                severity="medium",
                message="MACD crossed above signal line (bullish).",
                snapshot=snapshot,
            )
        ]
    if histogram[-2] > 0 >= histogram[-1]:
        return [
            Signal(
                name="MACD_BEAR_CROSS",
                ticker=ticker,
                severity="medium",
                message="MACD crossed below signal line (bearish).",
                snapshot=snapshot,
            )
        ]
    return []


# ─── Coppock Curve (monthly buy) ─────────────────────────────────────────────


def _roc(values: list[float], n: int) -> list[float]:
    if len(values) <= n:
        return []
    return [(values[i] / values[i - n] - 1.0) * 100.0 for i in range(n, len(values))]


def _wma(values: list[float], n: int) -> list[float]:
    if len(values) < n:
        return []
    weights = list(range(1, n + 1))
    wsum = sum(weights)
    out: list[float] = []
    for i in range(n - 1, len(values)):
        window = values[i - n + 1 : i + 1]
        out.append(sum(w * v for w, v in zip(weights, window)) / wsum)
    return out


def _coppock(closes: list[float], roc1: int = 14, roc2: int = 11, wma_n: int = 10) -> list[float]:
    r1 = _roc(closes, roc1)
    r2 = _roc(closes, roc2)
    if not r1 or not r2:
        return []
    # Align — both ROC lengths differ by (roc1 - roc2).
    if len(r2) > len(r1):
        r2 = r2[-len(r1) :]
    elif len(r1) > len(r2):
        r1 = r1[-len(r2) :]
    summed = [a + b for a, b in zip(r1, r2)]
    return _wma(summed, wma_n)


def _coppock_monthly(ticker: str, ohlc) -> list[Signal]:
    try:
        monthly = resample(ohlc, "ME")
    except ValueError:
        return []
    cs = _closes(monthly)
    if len(cs) < 36:
        return []
    curve = _coppock(cs)
    if len(curve) < 2:
        return []
    if curve[-2] <= 0 < curve[-1]:
        # COVID-period backtest: COPPOCK_BUY 60d edge was -28.24% — fired
        # at the very top before the crash continued. GFC fared OK (+10.30)
        # but n=42 is small. Downgrade severity until a confirmation filter
        # (e.g. SPY trend gate, or wait for monthly bar to close above
        # prior-month high) is added.
        return [
            Signal(
                name="COPPOCK_BUY",
                ticker=ticker,
                severity="low",
                message=(f"Coppock buy (curve {curve[-2]:.2f} → {curve[-1]:.2f}, monthly close {cs[-1]:.2f})."),
                snapshot={"prev": curve[-2], "current": curve[-1], "close": cs[-1]},
            )
        ]
    return []
