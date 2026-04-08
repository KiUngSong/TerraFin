"""Thin adapter: calls analytics computation, formats results as chart series dicts.

All chart-specific concerns (colors, priceScaleId, indicatorGroup, priceLevels)
live here.  The actual math lives in ``TerraFin.analytics.analysis.technical``.
"""

import math

from TerraFin.analytics.analysis.technical import (
    bollinger_bands,
    lppl,
    macd,
    mandelbrot_fractal_dimension,
    moving_average,
    range_vol,
    realized_vol,
    rsi,
    trend_signal_composite,
)


# ── Moving Averages ─────────────────────────────────────────────────────

_MA_WINDOWS = [20, 60, 120, 200]
_MA_COLORS = {20: "#ff9800", 60: "#9c27b0", 120: "#2196f3", 200: "#f44336"}


def compute_moving_averages(candle_data: list[dict]) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    items: list[dict] = []
    for window in _MA_WINDOWS:
        offset, values = moving_average(closes, window)
        if not values:
            continue
        data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(values)]
        items.append(
            {
                "id": f"MA {window}",
                "seriesType": "line",
                "color": _MA_COLORS[window],
                "data": data,
                "priceScaleId": "right",
                "indicator": True,
                "indicatorGroup": f"ma-{window}",
            }
        )
    return items


# ── RSI ─────────────────────────────────────────────────────────────────

_RSI_COLOR = "#e91e63"
_RSI_OB_COLOR = "#ef5350"
_RSI_OS_COLOR = "#26a69a"


def compute_rsi(candle_data: list[dict], window: int = 14) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    offset, values = rsi(closes, window)
    if not values:
        return []
    data = [{"time": times[offset + i], "value": round(v, 2)} for i, v in enumerate(values)]
    return [
        {
            "id": f"RSI {window}",
            "seriesType": "line",
            "color": _RSI_COLOR,
            "data": data,
            "priceScaleId": "rsi",
            "indicator": True,
            "indicatorGroup": "rsi",
            "priceLevels": [
                {"price": 70, "color": _RSI_OB_COLOR, "title": "Overbought"},
                {"price": 30, "color": _RSI_OS_COLOR, "title": "Oversold"},
            ],
        }
    ]


# ── Bollinger Bands ─────────────────────────────────────────────────────

_BB_UPPER_COLOR = "#26a69a"
_BB_LOWER_COLOR = "#ef5350"


def compute_bollinger_bands(candle_data: list[dict], window: int = 20, num_std: float = 2.0) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    offset, upper, lower = bollinger_bands(closes, window, num_std)
    if not upper:
        return []
    upper_data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(upper)]
    lower_data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(lower)]
    return [
        {
            "id": "BB Upper",
            "seriesType": "line",
            "color": _BB_UPPER_COLOR,
            "data": upper_data,
            "priceScaleId": "right",
            "indicator": True,
            "indicatorGroup": "bb",
        },
        {
            "id": "BB Lower",
            "seriesType": "line",
            "color": _BB_LOWER_COLOR,
            "data": lower_data,
            "priceScaleId": "right",
            "indicator": True,
            "indicatorGroup": "bb",
        },
    ]


# ── MACD ────────────────────────────────────────────────────────────────

_MACD_COLOR = "#2196f3"
_SIGNAL_COLOR = "#ff9800"
_HIST_UP_COLOR = "#26a69a"
_HIST_DOWN_COLOR = "#ef5350"


def compute_macd(candle_data: list[dict], fast: int = 12, slow: int = 26, signal_window: int = 9) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    offset, macd_vals, signal_vals, hist_vals = macd(closes, fast, slow, signal_window)
    if not macd_vals:
        return []

    macd_data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(macd_vals)]
    signal_data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(signal_vals)]
    hist_data = [
        {"time": times[offset + i], "value": round(v, 4), "color": _HIST_UP_COLOR if v >= 0 else _HIST_DOWN_COLOR}
        for i, v in enumerate(hist_vals)
    ]

    return [
        {
            "id": "Histogram",
            "seriesType": "histogram",
            "data": hist_data,
            "priceScaleId": "macd",
            "indicator": True,
            "indicatorGroup": "macd",
        },
        {
            "id": "MACD",
            "seriesType": "line",
            "color": _MACD_COLOR,
            "data": macd_data,
            "priceScaleId": "macd",
            "indicator": True,
            "indicatorGroup": "macd",
        },
        {
            "id": "Signal",
            "seriesType": "line",
            "color": _SIGNAL_COLOR,
            "data": signal_data,
            "priceScaleId": "macd",
            "indicator": True,
            "indicatorGroup": "macd",
        },
    ]


# ── Volatility ──────────────────────────────────────────────────────────

_REALIZED_VOL_COLOR = "#7e57c2"
_RANGE_VOL_COLOR = "#00897b"


def compute_realized_volatility(candle_data: list[dict], window: int = 21) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    offset, values = realized_vol(closes, window)
    if not values:
        return []
    data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(values)]
    return [
        {
            "id": "Realized Vol",
            "seriesType": "line",
            "color": _REALIZED_VOL_COLOR,
            "data": data,
            "priceScaleId": "vol",
            "indicator": True,
            "indicatorGroup": "realized-vol",
        }
    ]


def compute_range_volatility(candle_data: list[dict], window: int = 20) -> list[dict]:
    times, highs, lows = _extract_ohlc(candle_data)
    if not highs:
        return []
    offset, values = range_vol(highs, lows, window)
    if not values:
        return []
    data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(values)]
    return [
        {
            "id": "Range Vol",
            "seriesType": "line",
            "color": _RANGE_VOL_COLOR,
            "data": data,
            "priceScaleId": "vol",
            "indicator": True,
            "indicatorGroup": "range-vol",
        }
    ]


# ── Trend Signal ───────────────────────────────────────────────────────

_TREND_SIGNAL_COLOR = "#00bcd4"


def compute_trend_signal(candle_data: list[dict]) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []
    offset, values = trend_signal_composite(closes)
    if not values:
        return []
    data = [{"time": times[offset + i], "value": round(v, 4)} for i, v in enumerate(values)]
    return [
        {
            "id": "Trend Signal",
            "seriesType": "line",
            "color": _TREND_SIGNAL_COLOR,
            "data": data,
            "priceScaleId": "trend",
            "indicator": True,
            "indicatorGroup": "trend-signal",
            "priceLevels": [
                {"price": 0.0, "color": "#9e9e9e", "title": "Neutral"},
            ],
        }
    ]


# ── Mandelbrot Fractal Dimension ──────────────────────────────────────

_MFD_COLORS = {65: "#ff9800", 130: "#009688", 260: "#d81b60"}
_DEFAULT_CHART_MFD_WINDOWS = (130,)


def compute_mandelbrot_fractal_dimension(
    candle_data: list[dict],
    windows: tuple[int, ...] = _DEFAULT_CHART_MFD_WINDOWS,
) -> list[dict]:
    """Format MFD overlays for charts.

    The chart defaults to the medium-horizon 130-day window to keep the
    indicator pane readable. Callers such as the agent service can request the
    full multi-horizon set explicitly.
    """
    times, closes = _extract_close(candle_data)
    if not closes:
        return []

    items: list[dict] = []
    for window in windows:
        offset, values = mandelbrot_fractal_dimension(closes, window=window)
        if not values:
            continue
        data = [
            {"time": times[offset + i], "value": round(v, 4)}
            for i, v in enumerate(values)
            if math.isfinite(v)
        ]
        if not data:
            continue
        payload = {
            "id": f"MFD {window}",
            "seriesType": "line",
            "color": _MFD_COLORS.get(window, "#546e7a"),
            "data": data,
            "priceScaleId": "mfd",
            "indicator": True,
            "indicatorGroup": "mfd",
        }
        if not items:
            payload["priceLevels"] = [
                {"price": 1.0, "color": "#9e9e9e", "title": "Smooth"},
                {"price": 1.5, "color": "#bdbdbd", "title": "Random"},
                {"price": 2.0, "color": "#90a4ae", "title": "Choppy"},
            ]
        items.append(payload)
    return items


# ── LPPL Bubble Detection ──────────────────────────────────────────────

_LPPL_FIT_COLOR = "#d32f2f"


def compute_lppl_bubble(candle_data: list[dict]) -> list[dict]:
    times, closes = _extract_close(candle_data)
    if not closes:
        return []

    result = lppl(closes)
    if result.fit is None:
        return []
    data = [
        {"time": times[i], "value": round(math.exp(result.fit.fitted[i]), 4)}
        for i in range(len(closes))
        if result.fit.fitted[i] < 20  # guard against overflow
    ]
    return [
        {
            "id": "LPPL Fit",
            "seriesType": "line",
            "color": _LPPL_FIT_COLOR,
            "data": data,
            "priceScaleId": "right",
            "indicator": True,
            "indicatorGroup": "lppl",
        }
    ]


# ── Helpers ─────────────────────────────────────────────────────────────


def _extract_close(candle_data: list[dict]) -> tuple[list[str], list[float]]:
    """Extract aligned time and close lists from candlestick dicts."""
    points = [
        (p["time"], float(p["close"])) for p in candle_data if isinstance(p, dict) and "time" in p and "close" in p
    ]
    if not points:
        return ([], [])
    times, closes = zip(*points)
    return (list(times), list(closes))


def _extract_ohlc(candle_data: list[dict]) -> tuple[list[str], list[float], list[float]]:
    """Extract aligned time, high, and low lists from candlestick dicts."""
    points = [
        (p["time"], float(p["high"]), float(p["low"]))
        for p in candle_data
        if isinstance(p, dict) and "time" in p and "high" in p and "low" in p
    ]
    if not points:
        return ([], [], [])
    times, highs, lows = zip(*points)
    return (list(times), list(highs), list(lows))
