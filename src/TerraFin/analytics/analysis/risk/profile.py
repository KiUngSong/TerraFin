"""Statistical risk profiling from price data.

General-purpose capability: computes tail risk, convexity, volatility regime,
and drawdown analytics that any guru agent can invoke.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from TerraFin.analytics.analysis.technical.vol_regime import percentile_rank, vol_regime


@dataclass(frozen=True, slots=True)
class RiskProfileResult:
    ticker: str
    tail_risk: dict[str, Any]
    convexity: dict[str, Any]
    volatility: dict[str, Any]
    drawdown: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _safe(value: float) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return round(float(value), 4)


def _daily_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def _compute_tail_risk(returns: pd.Series) -> dict[str, Any]:
    if len(returns) < 30:
        return {"status": "insufficient_data"}

    arr = returns.values
    kurtosis = float(pd.Series(arr).kurtosis())
    skewness = float(pd.Series(arr).skew())

    sorted_returns = np.sort(arr)
    n = len(sorted_returns)
    idx_5 = max(int(n * 0.05) - 1, 0)
    idx_95 = min(int(n * 0.95), n - 1)
    var_95 = float(sorted_returns[idx_5])
    cvar_95 = float(sorted_returns[: idx_5 + 1].mean()) if idx_5 >= 0 else var_95

    tail_ratio = (
        abs(float(sorted_returns[idx_95])) / abs(var_95) if var_95 != 0 else None
    )

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / running_max
    max_drawdown = float(drawdowns.min())

    return {
        "kurtosis": _safe(kurtosis),
        "skewness": _safe(skewness),
        "var_95_daily": _safe(var_95),
        "cvar_95_daily": _safe(cvar_95),
        "tail_ratio": _safe(tail_ratio) if tail_ratio is not None else None,
        "max_drawdown_pct": _safe(max_drawdown * 100),
    }


def _compute_convexity(returns: pd.Series, benchmark_returns: pd.Series | None = None) -> dict[str, Any]:
    if len(returns) < 30:
        return {"status": "insufficient_data"}

    positive_returns = returns[returns > 0]
    negative_returns = returns[returns < 0]

    avg_up = float(positive_returns.mean()) if len(positive_returns) > 0 else 0.0
    avg_down = float(negative_returns.mean()) if len(negative_returns) > 0 else 0.0
    return_asymmetry = avg_up / abs(avg_down) if avg_down != 0 else None

    upside_capture = None
    downside_capture = None
    if benchmark_returns is not None and len(benchmark_returns) >= 30:
        aligned = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
        if len(aligned) >= 30:
            aligned.columns = ["asset", "benchmark"]
            up_mask = aligned["benchmark"] > 0
            down_mask = aligned["benchmark"] < 0

            if up_mask.sum() > 5:
                upside_capture = float(aligned.loc[up_mask, "asset"].mean() / aligned.loc[up_mask, "benchmark"].mean())
            if down_mask.sum() > 5:
                downside_capture = float(
                    aligned.loc[down_mask, "asset"].mean() / aligned.loc[down_mask, "benchmark"].mean()
                )

    return {
        "return_asymmetry": _safe(return_asymmetry) if return_asymmetry is not None else None,
        "avg_up_day_pct": _safe(avg_up * 100),
        "avg_down_day_pct": _safe(avg_down * 100),
        "upside_capture_ratio": _safe(upside_capture) if upside_capture is not None else None,
        "downside_capture_ratio": _safe(downside_capture) if downside_capture is not None else None,
    }


def _compute_volatility(prices: pd.Series, returns: pd.Series) -> dict[str, Any]:
    if len(returns) < 30:
        return {"status": "insufficient_data"}

    ann_vol = float(returns.std() * math.sqrt(252))

    rolling_vol_20 = returns.rolling(20).std() * math.sqrt(252)
    rolling_vol_values = rolling_vol_20.dropna().tolist()

    if len(rolling_vol_values) >= 126:
        offset, ranks = percentile_rank(rolling_vol_values, window=126)
        vol_pct_rank = ranks[-1] if ranks else None
    elif len(rolling_vol_values) >= 20:
        offset, ranks = percentile_rank(rolling_vol_values, window=len(rolling_vol_values))
        vol_pct_rank = ranks[-1] if ranks else None
    else:
        vol_pct_rank = None

    vol_of_vol = None
    if len(rolling_vol_values) >= 30:
        vol_series = pd.Series(rolling_vol_values)
        vol_of_vol = float(vol_series.std() / vol_series.mean()) if vol_series.mean() != 0 else None

    regime_label = "unknown"
    if len(rolling_vol_values) >= 126:
        _, regimes = vol_regime(rolling_vol_values, window=126)
        if regimes:
            regime_label = "stable" if regimes[-1] == 1 else "unstable"
    elif len(rolling_vol_values) >= 20:
        _, regimes = vol_regime(rolling_vol_values, window=len(rolling_vol_values))
        if regimes:
            regime_label = "stable" if regimes[-1] == 1 else "unstable"

    return {
        "annualized_vol_pct": _safe(ann_vol * 100),
        "vol_percentile_rank": _safe(vol_pct_rank) if vol_pct_rank is not None else None,
        "vol_of_vol": _safe(vol_of_vol) if vol_of_vol is not None else None,
        "regime": regime_label,
    }


def _compute_drawdown(prices: pd.Series) -> dict[str, Any]:
    if len(prices) < 10:
        return {"status": "insufficient_data"}

    cumulative = prices / prices.iloc[0]
    running_max = cumulative.cummax()
    drawdown_series = (cumulative - running_max) / running_max

    current_dd = float(drawdown_series.iloc[-1])
    max_dd = float(drawdown_series.min())
    max_dd_idx = drawdown_series.idxmin()

    recovery_days = None
    if max_dd < -0.01:
        post_trough = prices.loc[max_dd_idx:]
        peak_before = running_max.loc[max_dd_idx] * prices.iloc[0]
        recovered = post_trough[post_trough >= peak_before]
        if len(recovered) > 0:
            recovery_days = (recovered.index[0] - max_dd_idx).days

    return {
        "current_drawdown_pct": _safe(current_dd * 100),
        "max_drawdown_pct": _safe(max_dd * 100),
        "max_drawdown_date": str(max_dd_idx.date()) if hasattr(max_dd_idx, "date") else str(max_dd_idx),
        "recovery_days": recovery_days,
        "recovered": recovery_days is not None,
    }


def run_risk_profile(
    ticker: str,
    prices: pd.Series,
    *,
    benchmark_prices: pd.Series | None = None,
) -> RiskProfileResult:
    """Compute a full risk profile from a price series."""
    warnings: list[str] = []

    if prices is None or len(prices) < 30:
        return RiskProfileResult(
            ticker=ticker,
            tail_risk={"status": "insufficient_data"},
            convexity={"status": "insufficient_data"},
            volatility={"status": "insufficient_data"},
            drawdown={"status": "insufficient_data"},
            warnings=["Insufficient price data (need at least 30 observations)."],
        )

    returns = _daily_returns(prices)

    benchmark_returns = None
    if benchmark_prices is not None and len(benchmark_prices) >= 30:
        benchmark_returns = _daily_returns(benchmark_prices)
    else:
        if benchmark_prices is not None:
            warnings.append("Benchmark data insufficient; capture ratios unavailable.")

    return RiskProfileResult(
        ticker=ticker,
        tail_risk=_compute_tail_risk(returns),
        convexity=_compute_convexity(returns, benchmark_returns),
        volatility=_compute_volatility(prices, returns),
        drawdown=_compute_drawdown(prices),
        warnings=warnings,
    )
