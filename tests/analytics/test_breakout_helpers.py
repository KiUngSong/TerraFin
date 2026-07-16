"""Tests for the pure 52-week-high core and the trend-gated weekly volume
dry-up detector (breakout.py)."""

import pandas as pd

from TerraFin.analytics.analysis.patterns._base import entered_extreme
from TerraFin.analytics.analysis.patterns.breakout import (
    detect_weekly_volume_dryup,
    evaluate,
    fifty_two_week_high_status,
)


def _ohlc(closes, volumes=None, index=None):
    """Daily OHLC frame from a close series (volume optional, defaults flat)."""
    n = len(closes)
    idx = index if index is not None else pd.date_range("2024-01-01", periods=n, freq="D")
    vol = volumes if volumes is not None else [1_000_000] * n
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": vol,
        },
        index=idx,
    )


# ── fifty_two_week_high_status ──────────────────────────────────────────


def test_52w_status_none_when_short():
    """Fewer than 252 bars → None, never a fake 52-week stat off a short window."""
    assert fifty_two_week_high_status(_ohlc([100.0] * 200)) is None


def test_52w_status_new_high():
    """A series climbing to a fresh top on the last bar flags new_high."""
    closes = [100.0 + i * 0.1 for i in range(300)]  # strictly rising → last is the max
    st = fifty_two_week_high_status(_ohlc(closes))
    assert st is not None
    assert st["new_high"] is True
    assert st["above_50dma"] is True
    assert abs(st["pct_from_high"]) < 1e-9  # at the high


def test_52w_status_below_high_not_new():
    """Price well off the trailing high → not a new high, negative pct_from_high."""
    closes = [100.0 + i * 0.1 for i in range(280)] + [110.0] * 20  # peaked then drifted under
    st = fifty_two_week_high_status(_ohlc(closes))
    assert st is not None
    assert st["new_high"] is False
    assert st["pct_from_high"] < 0.0


# ── 52W_NEW_LOW (mirror of 52W_NEW_HIGH) ────────────────────────────────


def test_52w_new_low_fires_on_fresh_low_below_50dma():
    """A series grinding to a fresh 252-day low on the last bar → 52W_NEW_LOW."""
    closes = [200.0 - i * 0.2 for i in range(303)]  # strictly falling → last is the min
    names = {s.name for s in evaluate("TEST", _ohlc(closes))}
    assert "52W_NEW_LOW" in names


def test_52w_new_low_absent_when_not_a_new_low():
    """Rising series → last bar is a high, never a new low."""
    closes = [100.0 + i * 0.2 for i in range(303)]
    names = {s.name for s in evaluate("TEST", _ohlc(closes))}
    assert "52W_NEW_LOW" not in names


# ── detect_weekly_volume_dryup ──────────────────────────────────────────


def test_weekly_dryup_uptrend_constructive():
    """Uptrend + recent weekly volume collapsing vs the base → constructive dry-up."""
    # ~300 daily bars rising; volume high early, dried up over the last ~8 weeks.
    closes = [100.0 + i * 0.2 for i in range(300)]
    vols = [2_000_000] * 260 + [400_000] * 40  # last ~5-6 weeks light
    st = detect_weekly_volume_dryup(_ohlc(closes, vols))
    assert st is not None
    assert st["dryup"] is True
    assert st["ratio"] <= 0.6


def test_weekly_dryup_downtrend_suppressed():
    """Same volume collapse but in a DOWNTREND → suppressed (sign would be wrong)."""
    closes = [160.0 - i * 0.2 for i in range(300)]  # falling
    vols = [2_000_000] * 260 + [400_000] * 40
    assert detect_weekly_volume_dryup(_ohlc(closes, vols)) is None


def test_weekly_dryup_no_collapse_returns_none():
    """Uptrend but volume steady → no dry-up."""
    closes = [100.0 + i * 0.2 for i in range(300)]
    assert detect_weekly_volume_dryup(_ohlc(closes, [1_000_000] * 300)) is None


def test_weekly_dryup_ignores_partial_trailing_week():
    """A partial current-week bar must not change the verdict — otherwise the
    signal fires or not depending on which weekday the scan runs."""
    idx = pd.bdate_range("2024-01-05", periods=300)  # starts on a Friday
    while idx[-1].weekday() != 4:  # trim so the series ENDS on a Friday (full week)
        idx = idx[:-1]
    n = len(idx)
    closes = [100.0 + i * 0.2 for i in range(n)]
    vols = [2_000_000] * (n - 20) + [400_000] * 20  # recent weeks dried up
    friday_verdict = detect_weekly_volume_dryup(_ohlc(closes, vols, idx)) is not None
    assert friday_verdict is True  # the full-week series fires

    # Append a partial next week (Mon+Tue) of HUGE volume. Counting it would
    # flip the verdict to None; dropping the partial bar keeps it True.
    extra = pd.bdate_range(idx[-1] + pd.Timedelta(days=3), periods=2)
    idx2 = idx.append(extra)
    closes2 = closes + [closes[-1] + 0.2, closes[-1] + 0.4]
    vols2 = vols + [50_000_000, 50_000_000]
    partial_verdict = detect_weekly_volume_dryup(_ohlc(closes2, vols2, idx2)) is not None
    assert partial_verdict == friday_verdict


def test_weekly_dryup_emitted_as_monitoring_signal():
    """The detector surfaces as a WEEKLY_VOLUME_DRYUP signal from evaluate()."""
    closes = [100.0 + i * 0.2 for i in range(300)]
    vols = [2_000_000] * 260 + [400_000] * 40
    sigs = [s for s in evaluate("TEST", _ohlc(closes, vols)) if s.name == "WEEKLY_VOLUME_DRYUP"]
    assert sigs, "WEEKLY_VOLUME_DRYUP should fire"
    # Must be >= medium or DataFactory's eod_scan drops it before any alert.
    assert sigs[0].severity == "medium"


# ─── entered_extreme (variant-agnostic fresh-entry primitive) ─────────────


def test_entered_extreme_fresh_oversold_cross():
    # in-zone now, out-of-zone within the window -> fresh entry
    assert entered_extreme([40, 38, 36, 34, 32, 28], threshold=30, low=True, lookback=5) is True


def test_entered_extreme_rejects_parked_in_zone():
    # sat <=30 the whole window -> NOT a fresh entry
    assert entered_extreme([28, 27, 26, 25, 24, 23], threshold=30, low=True, lookback=5) is False


def test_entered_extreme_counts_bounce_out_and_back():
    # popped >30 mid-window then re-entered -> still fresh (whole-window scan, not endpoints)
    assert entered_extreme([28, 45, 29, 28, 27, 29], threshold=30, low=True, lookback=5) is True


def test_entered_extreme_overbought_side():
    assert entered_extreme([50, 60, 68, 72, 74, 77], threshold=70, low=False, lookback=5) is True
    assert entered_extreme([72, 73, 74, 75, 76, 77], threshold=70, low=False, lookback=5) is False


def test_entered_extreme_series_shorter_than_lookback():
    assert entered_extreme([40, 50], threshold=30, low=True, lookback=5) is False


def test_entered_extreme_nan_in_window_returns_false():
    # NaN makes min/max order-dependent -> must fail closed, not silently flag/skip.
    assert entered_extreme([28, float("nan"), 29, 28, 27, 29], threshold=30, low=True, lookback=5) is False
