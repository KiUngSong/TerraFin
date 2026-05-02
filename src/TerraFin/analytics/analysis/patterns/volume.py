"""Volume conditions — capitulation, OBV divergence, CMF, MFI."""

from ._base import (
    Signal,
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
    out.extend(_capitulation_bottom(ticker, ohlc))
    out.extend(_obv_trend_break(ticker, ohlc))
    out.extend(_chaikin_money_flow(ticker, ohlc))
    out.extend(_money_flow_index(ticker, ohlc))
    return out


# ─── Capitulation bottom (Wyckoff Selling Climax) ────────────────────────────


def _capitulation_bottom(
    ticker: str,
    ohlc,
    *,
    vol_window: int = 20,
    vol_zscore: float = 2.5,
    prior_window: int = 20,
    max_prior_return: float = 0.0,
    min_range_position: float = 0.4,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vols = _volumes(ohlc)
    if vols is None or len(cs) < max(vol_window, prior_window) + 2:
        return []
    if not (len(vols) == len(cs) == len(hs) == len(ls)):
        return []
    # Wyckoff selling-climax shape filter — close must be in the upper
    # ``min_range_position`` of the bar's range (rejection of the low). In
    # COVID's March 2020 sustained-decline window the unfiltered version
    # fired into still-falling bars (60d edge -7.96% in backtest); requiring
    # an upper-half close shifts to genuine reversal candles.
    bar_range = hs[-1] - ls[-1]
    if bar_range > 0:
        range_pos = (cs[-1] - ls[-1]) / bar_range
        if range_pos < min_range_position:
            return []

    # Volume z-score over prior ``vol_window`` bars (excluding the current bar
    # so a spike doesn't poison its own baseline).
    window_vols = vols[-(vol_window + 1) : -1]
    if len(window_vols) < vol_window:
        return []
    mean = sum(window_vols) / vol_window
    var = sum((v - mean) ** 2 for v in window_vols) / vol_window
    std = var**0.5
    if std <= 0:
        return []
    cur_vol = vols[-1]
    z = (cur_vol - mean) / std
    if z < vol_zscore:
        return []

    # Prior trend: net return over ``prior_window`` bars must be non-positive
    # (filters out distribution-day false positives in uptrends).
    prior_close = cs[-(prior_window + 1)]
    if prior_close <= 0:
        return []
    prior_ret = (cs[-1] - prior_close) / prior_close
    if prior_ret > max_prior_return:
        return []

    return [
        Signal(
            name="CAPITULATION_BOTTOM",
            ticker=ticker,
            severity="high",
            message=(f"Capitulation: vol z={z:.1f}σ after {prior_ret * 100:+.1f}% over {prior_window} bars."),
            snapshot={
                "close": cs[-1],
                "bar_volume": cur_vol,
                "rolling_avg_volume": mean,
                "vol_zscore": round(z, 2),
                "prior_window": prior_window,
                "prior_return_pct": round(prior_ret * 100, 2),
            },
        )
    ]


# ─── OBV trend break vs price (Granville divergence) ─────────────────────────


def _slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def _obv_trend_break(
    ticker: str,
    ohlc,
    *,
    lookback: int = 20,
    min_obv_slope_z: float = 1.0,
) -> list[Signal]:
    cs = _closes(ohlc)
    vols = _volumes(ohlc)
    if vols is None or len(cs) < lookback * 5 or len(vols) != len(cs):
        return []

    # Build OBV running series.
    obv = [0.0]
    for i in range(1, len(cs)):
        if cs[i] > cs[i - 1]:
            obv.append(obv[-1] + vols[i])
        elif cs[i] < cs[i - 1]:
            obv.append(obv[-1] - vols[i])
        else:
            obv.append(obv[-1])

    price_window = cs[-lookback:]
    obv_window = obv[-lookback:]
    price_slope = _slope(price_window)
    obv_slope = _slope(obv_window)
    if price_slope * obv_slope >= 0:
        return []

    # Z-score gate: |obv_slope| must stand out vs recent rolling slopes.
    sample_count = lookback * 5
    abs_slopes: list[float] = []
    for end in range(lookback, len(obv) + 1):
        abs_slopes.append(abs(_slope(obv[end - lookback : end])))
    abs_slopes = abs_slopes[-sample_count:]
    if len(abs_slopes) < lookback:
        return []
    mean = sum(abs_slopes) / len(abs_slopes)
    var = sum((v - mean) ** 2 for v in abs_slopes) / len(abs_slopes)
    std = var**0.5
    if std > 0 and (abs(obv_slope) - mean) / std < min_obv_slope_z:
        return []

    kind = "bullish" if obv_slope > 0 > price_slope else "bearish"
    return [
        Signal(
            name="OBV_DIVERGENCE",
            ticker=ticker,
            severity="low",
            message=(
                f"OBV {kind} divergence over {lookback} bars "
                f"(price slope {price_slope:+.4f}, OBV slope {obv_slope:+.0f})."
            ),
            snapshot={
                "lookback": lookback,
                "price_slope": price_slope,
                "obv_slope": obv_slope,
                "kind": kind,
            },
        )
    ]


# ─── Chaikin Money Flow (CMF) ────────────────────────────────────────────────


def _chaikin_money_flow(
    ticker: str,
    ohlc,
    *,
    period: int = 20,
    threshold: float = 0.05,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if vs is None or len(cs) < period + 2:
        return []
    if not (len(cs) == len(hs) == len(ls) == len(vs)):
        return []

    def _cmf_at(end_idx: int) -> float | None:
        if end_idx + 1 < period:
            return None
        s_mfv = 0.0
        s_v = 0.0
        for i in range(end_idx - period + 1, end_idx + 1):
            rng = hs[i] - ls[i]
            if rng <= 0:
                continue
            mfv = (((cs[i] - ls[i]) - (hs[i] - cs[i])) / rng) * vs[i]
            s_mfv += mfv
            s_v += vs[i]
        if s_v <= 0:
            return None
        return s_mfv / s_v

    cur = _cmf_at(len(cs) - 1)
    prev = _cmf_at(len(cs) - 2)
    if cur is None or prev is None:
        return []
    if prev <= threshold < cur:
        return [
            Signal(
                name="CMF_ACCUMULATION",
                ticker=ticker,
                severity="medium",
                message=(
                    f"Chaikin Money Flow crossed +{threshold:.2f} (now {cur:.3f}) — "
                    f"institutional accumulation signature."
                ),
                snapshot={"cmf": cur, "prev": prev},
            )
        ]
    if prev >= -threshold > cur:
        return [
            Signal(
                name="CMF_DISTRIBUTION",
                ticker=ticker,
                severity="medium",
                message=(f"Chaikin Money Flow crossed -{threshold:.2f} (now {cur:.3f}) — distribution signature."),
                snapshot={"cmf": cur, "prev": prev},
            )
        ]
    return []


# ─── Money Flow Index (MFI) ──────────────────────────────────────────────────


def _money_flow_index(
    ticker: str,
    ohlc,
    *,
    period: int = 14,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> list[Signal]:
    cs = _closes(ohlc)
    hs = _highs(ohlc)
    ls = _lows(ohlc)
    vs = _volumes(ohlc)
    if vs is None or len(cs) < period + 2:
        return []
    if not (len(cs) == len(hs) == len(ls) == len(vs)):
        return []

    def _mfi_at(end_idx: int) -> float | None:
        if end_idx + 1 < period + 1:
            return None
        pos_flow = 0.0
        neg_flow = 0.0
        for i in range(end_idx - period + 1, end_idx + 1):
            tp = (hs[i] + ls[i] + cs[i]) / 3.0
            tp_prev = (hs[i - 1] + ls[i - 1] + cs[i - 1]) / 3.0
            mf = tp * vs[i]
            if tp > tp_prev:
                pos_flow += mf
            elif tp < tp_prev:
                neg_flow += mf
        if neg_flow == 0:
            return 100.0
        mfr = pos_flow / neg_flow
        return 100 - 100 / (1 + mfr)

    cur = _mfi_at(len(cs) - 1)
    prev = _mfi_at(len(cs) - 2)
    if cur is None or prev is None:
        return []
    # Edge-trigger entry into overbought/oversold zones.
    if prev < overbought <= cur:
        return [
            Signal(
                name="MFI_OVERBOUGHT",
                ticker=ticker,
                severity="medium",
                message=f"MFI {cur:.1f} entered overbought (≥{overbought:.0f}).",
                snapshot={"mfi": cur, "prev": prev},
            )
        ]
    if prev > oversold >= cur:
        return [
            Signal(
                name="MFI_OVERSOLD",
                ticker=ticker,
                severity="medium",
                message=f"MFI {cur:.1f} entered oversold (≤{oversold:.0f}).",
                snapshot={"mfi": cur, "prev": prev},
            )
        ]
    return []
