"""Guards for the pattern catalogue's facts about itself.

`signal_key` states which detections are one finding; `PATTERN_TIMEFRAMES`
states which timeframe each pattern belongs to. Both are read out of repo, so a
name the catalogue can emit but the map omits fails only over there.
"""

import re
from pathlib import Path

import pytest

from TerraFin.analytics.analysis import patterns as patterns_pkg
from TerraFin.analytics.analysis.patterns import PATTERN_TIMEFRAMES, signal_key
from TerraFin.analytics.analysis.patterns._base import Signal


PATTERNS_DIR = Path(patterns_pkg.__file__).parent


def _sig(name="WEEKLY_NEW_HIGH", ticker="NVDA", **snapshot):
    return Signal(name=name, ticker=ticker, severity="high", message="m", snapshot=snapshot)


def test_trigger_bar_outranks_the_data_week():
    """A divergence re-confirms on three consecutive weekly bars off one pivot.

    Keyed on `week_ending` that is three findings; keyed on the pivot bar it is
    one, which is what it is.
    """
    keys = {
        signal_key(
            _sig(
                name="WEEKLY_RSI_BULL_DIVERGENCE",
                trigger_bar="2026-08-21",
                week_ending=week,
            )
        )
        for week in ("2026-08-28", "2026-09-04", "2026-09-11")
    }
    assert keys == {"2026-08-21"}


def test_week_ending_is_the_key_when_there_is_no_trigger_bar():
    assert signal_key(_sig(week_ending="2026-09-04")) == "2026-09-04"


def test_two_data_weeks_are_two_keys():
    a = signal_key(_sig(week_ending="2026-09-04"))
    b = signal_key(_sig(week_ending="2026-09-11"))
    assert a != b


def test_an_unkeyable_signal_returns_none_rather_than_inventing_one():
    """A daily pattern carries neither field. Returning a run-derived stand-in
    here would silently make the consumer's fallback unreachable.
    """
    assert signal_key(_sig(name="52W_NEW_HIGH", close=1.0)) is None
    assert signal_key(_sig(name="52W_NEW_HIGH")) is None
    # An empty string is as unkeyable as a missing field.
    assert signal_key(_sig(trigger_bar="", week_ending="")) is None


def _emittable_pattern_names() -> set[str]:
    names: set[str] = set()
    for f in PATTERNS_DIR.glob("*.py"):
        if f.name in ("__init__.py", "_base.py", "catalog.py"):
            continue
        names |= set(re.findall(r'name="([A-Z0-9_]+)"', f.read_text()))
    # The MA-cross grid and the divergence pair build their names by f-string,
    # so expand them from the lists that drive those loops.
    from TerraFin.analytics.analysis.patterns import trend

    for p in trend._DAILY_MA_PERIODS:
        names |= {f"MA{p}_GOLDEN_CROSS", f"MA{p}_DEATH_CROSS"}
    for p in trend._WEEKLY_MA_PERIODS:
        names |= {f"MA{p}W_GOLDEN_CROSS", f"MA{p}W_DEATH_CROSS"}
    for prefix in ("", "WEEKLY_"):
        names |= {f"{prefix}RSI_BULL_DIVERGENCE", f"{prefix}RSI_BEAR_DIVERGENCE"}
    return names


def test_the_map_covers_the_catalogue_exactly():
    """Both directions. A missing name is dropped by the consumer's timeframe
    filter; a surplus one is a rule kept alive for a pattern that is gone.
    """
    emittable = _emittable_pattern_names()
    assert emittable, "no pattern names discovered — layout changed?"
    assert emittable - set(PATTERN_TIMEFRAMES) == set()
    assert set(PATTERN_TIMEFRAMES) - emittable == set()


def test_declared_timeframes_are_pinned():
    """Re-tagging a weekly pattern as daily would otherwise pass silently."""
    assert {n for n, tf in PATTERN_TIMEFRAMES.items() if tf == "weekly"} == {
        "MA20W_GOLDEN_CROSS",
        "MA20W_DEATH_CROSS",
        "MA60W_GOLDEN_CROSS",
        "MA60W_DEATH_CROSS",
        "MA120W_GOLDEN_CROSS",
        "MA120W_DEATH_CROSS",
        "WEEKLY_VOLUME_DRYUP",
        "WEEKLY_NEW_HIGH",
        "WEEKLY_NEW_LOW",
        "WEEKLY_RSI_BULL_DIVERGENCE",
        "WEEKLY_RSI_BEAR_DIVERGENCE",
    }
    assert set(PATTERN_TIMEFRAMES.values()) == {"daily", "weekly"}


@pytest.mark.parametrize("name", sorted(PATTERN_TIMEFRAMES))
def test_the_key_carries_no_ticker_or_pattern_of_its_own(name):
    """The key states the bar, never the identity around it — a consumer
    prefixes its own ticker and pattern.
    """
    key = signal_key(_sig(name=name, trigger_bar="2026-09-04"))
    assert key == "2026-09-04"


@pytest.mark.parametrize("name", sorted(n for n, tf in PATTERN_TIMEFRAMES.items() if tf != "weekly"))
def test_a_daily_pattern_is_not_keyed_by_a_week_it_happens_to_report(name):
    """Keying a daily fire on the week would ship it once instead of once a
    day, and nothing downstream can tell.
    """
    assert signal_key(_sig(name=name, week_ending="2026-09-04")) is None


@pytest.mark.parametrize("name", sorted(n for n, tf in PATTERN_TIMEFRAMES.items() if tf == "weekly"))
def test_a_weekly_pattern_falls_back_to_its_data_week(name):
    assert signal_key(_sig(name=name, week_ending="2026-09-04")) == "2026-09-04"


def test_a_real_detector_emits_a_trigger_bar_on_a_production_frame():
    """The frame the monitor passes keeps time as a column under a RangeIndex,
    not as the index. Read the index directly and every key is silently None.
    """
    import numpy as np
    import pandas as pd

    from TerraFin.analytics.analysis.patterns import reversal

    def seg(a, b, n):
        # Exclusive of the start: a duplicated joint is never strictly extreme,
        # so `swing_pivots` would confirm no pivot at the turn.
        return list(np.linspace(a, b, n + 1))[1:]

    # Crash, bounce, then a lower price low on weaker momentum — a bull
    # divergence whose pivot lands inside the fire window.
    closes = [100.0] + seg(100, 100.5, 39) + seg(100.5, 55, 25) + seg(55, 80, 15) + seg(80, 52, 30) + seg(52, 62, 5)
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2020-01-01", periods=len(closes), freq="B"),
            "open": closes,
            "high": np.array(closes) * 1.01,
            "low": np.array(closes) * 0.99,
            "close": closes,
            "volume": 1e6,
        }
    )
    assert isinstance(frame.index, pd.RangeIndex)

    # Pinned to the pair, not to "some ISO string": the weekly branch keys off
    # `week_ending`, which never touches `bar_date`, so a substituted weekly
    # emission would satisfy a looser assertion with the bug reinstated.
    keyed = [(s.name, signal_key(s)) for s in reversal.evaluate("AAA", frame)]
    assert keyed == [("RSI_BULL_DIVERGENCE", "2020-06-02")], (
        "if the series stopped producing this pivot, adjust the fixture, not the assertion"
    )
