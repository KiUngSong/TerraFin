"""Weekly-timeframe patterns: `WEEKLY_NEW_HIGH/LOW` and weekly RSI divergence.

The first version of `_weekly_new_extreme` compared `cs[-2]` to its OWN trailing
window, which is true throughout any steady advance — so the detector never
fired on the case it exists for. These tests pin the daily signal's semantics
instead: `cs[-2] < high` against the SAME window.
"""

import numpy as np
import pandas as pd
import pytest

from TerraFin.analytics.analysis.patterns import breakout, reversal
from TerraFin.analytics.analysis.patterns._base import is_krx_ticker, weekly_bars


def _frame(closes, *, start="2020-01-01", volume=1e6):
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "time": idx,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [volume] * len(closes),
        }
    ).set_index("time")


def _ramp(a, b, n):
    return list(np.linspace(a, b, n))


# ── weekly_bars ──────────────────────────────────────────────────────────────


def test_weekly_bars_drops_a_partial_trailing_week():
    # Wednesday end date: the current week has not reached Friday.
    frame = _frame(_ramp(100, 200, 400), start="2020-01-01")
    weekly = weekly_bars(frame)
    assert weekly.index[-1].date() <= frame.index[-1].date()


def test_weekly_bars_never_reports_a_week_still_in_progress():
    """The reported week's final SESSION must already have data.

    The Friday label itself may sit past the last data date when that Friday
    was a holiday — 2022-04-15 was Good Friday — so the label is not the
    invariant; the week's last actual session is.

    The completed week is also NOT stable across run weekdays: on Thursday you
    genuinely lack Friday's close. That is why the EOD dedup keys on the data
    week rather than the run date.
    """
    from TerraFin.data.providers.market.sessions import last_session_on_or_before

    closes = _ramp(100, 300, 600)
    labels = []
    for offset in range(0, 6):
        frame = _frame(closes[: 600 - offset])
        weekly = weekly_bars(frame)
        label = weekly.index[-1].date()
        final = last_session_on_or_before(label)
        if final is not None:
            assert final <= frame.index[-1].date()
        labels.append(label)

    # Truncating more data can only move the completed week backwards.
    assert labels == sorted(labels, reverse=True)
    # And it does move, so a run-date key would split one week across two.
    assert len(set(labels)) > 1


# ── WEEKLY_NEW_HIGH / WEEKLY_NEW_LOW ─────────────────────────────────────────


def test_steady_advance_fires_weekly_new_high():
    """The regression the first implementation failed."""
    fired = breakout._weekly_new_extreme("AAA", _frame(_ramp(100, 400, 700)))
    assert [s.name for s in fired] == ["WEEKLY_NEW_HIGH"]
    assert fired[0].severity == "high"


def test_steady_decline_fires_weekly_new_low():
    fired = breakout._weekly_new_extreme("AAA", _frame(_ramp(400, 100, 700)))
    assert [s.name for s in fired] == ["WEEKLY_NEW_LOW"]
    assert fired[0].severity == "high"


def test_mid_range_does_not_fire():
    """Current close is neither the max nor the min of the last 52 WEEKS.

    The window matters: a long-run midpoint can still be a 52-week extreme, so
    the recent window has to contain both a higher high and a lower low.
    """
    closes = _ramp(100, 400, 500) + _ramp(400, 200, 150) + _ramp(200, 300, 100)
    weekly = weekly_bars(_frame(closes))
    recent = [float(v) for v in weekly["close"].tail(52)]
    assert min(recent) < recent[-1] < max(recent), "fixture is not mid-range"
    assert breakout._weekly_new_extreme("AAA", _frame(closes)) == []


def test_short_history_does_not_fire():
    assert breakout._weekly_new_extreme("AAA", _frame(_ramp(100, 200, 80))) == []


def test_a_kr_name_is_gated_on_kospi_and_a_us_name_on_spy(monkeypatch):
    """Each name is gated on the market it trades in.

    Gating a KRX name on a US index measures the wrong market; dropping the
    gate for it restores the ungated configuration the bear-period backtests
    found negative-edge. The gate has to be driven from the test — live it
    reads True, and None offline, so the suppressing branch is otherwise
    unreachable.
    """
    advance = _frame(_ramp(100, 400, 700))

    # KOSPI down, SPY up: the KR name is suppressed, the US name is not.
    monkeypatch.setattr(
        breakout,
        "venue_trend_ok",
        lambda ticker, period=50: False if is_krx_ticker(ticker) else True,
    )
    assert breakout._weekly_new_extreme("005930.KS", advance) == []
    assert breakout._fifty_two_week_new_high("005930.KS", advance) == []
    # Lowercase suffix must read the same, or the venues swap.
    assert breakout._weekly_new_extreme("005930.ks", advance) == []
    assert [s.name for s in breakout._weekly_new_extreme("NVDA", advance)] == ["WEEKLY_NEW_HIGH"]

    # SPY down, KOSPI up: the mirror image.
    monkeypatch.setattr(
        breakout,
        "venue_trend_ok",
        lambda ticker, period=50: True if is_krx_ticker(ticker) else False,
    )
    assert [s.name for s in breakout._weekly_new_extreme("005930.KS", advance)] == ["WEEKLY_NEW_HIGH"]
    assert [s.name for s in breakout._fifty_two_week_new_high("005930.KS", advance)] == ["52W_NEW_HIGH"]
    assert breakout._weekly_new_extreme("NVDA", advance) == []
    assert breakout._fifty_two_week_new_high("NVDA", advance) == []

    # Unknown regime never suppresses: an unavailable index must not silence
    # every bullish entry.
    monkeypatch.setattr(breakout, "venue_trend_ok", lambda ticker, period=50: None)
    assert [s.name for s in breakout._weekly_new_extreme("NVDA", advance)] == ["WEEKLY_NEW_HIGH"]


def test_the_gate_reads_each_names_own_index(monkeypatch):
    """The venue split itself, not the detectors that consult it.

    Patching `venue_trend_ok` — which the detector tests do — never runs this
    choice, so without this a gate that always read SPY would pass everything.
    """
    from TerraFin.analytics.analysis.patterns import _base

    asked = []
    monkeypatch.setattr(_base, "index_trend_ok", lambda symbol, period=50: asked.append(symbol))

    _base.venue_trend_ok("005930.KS")
    _base.venue_trend_ok("005930.ks")
    _base.venue_trend_ok("005930")
    _base.venue_trend_ok("038290.KQ")
    _base.venue_trend_ok("038290.kq")
    _base.venue_trend_ok("NVDA")
    # Not KRX despite the suffix, and a missing ticker: both fall to SPY rather
    # than reaching a KRX board or raising. `is_krx_ticker` decides the shape.
    _base.venue_trend_ok("ABC.KQ")
    _base.venue_trend_ok(None)
    # Padded: this branch strips on its own. `is_krx_ticker` strips too, so a
    # padded KOSDAQ name passes the KRX gate either way and would land on the
    # wrong board unnoticed.
    _base.venue_trend_ok(" 038290.KQ ")
    # KOSDAQ is its own board: its close-vs-SMA verdict differs from KOSPI's on
    # about a fifth of sessions, so one must not answer for the other.
    assert asked == ["^KS11", "^KS11", "^KS11", "^KQ11", "^KQ11", "SPY", "SPY", "SPY", "^KQ11"]

    asked.clear()
    _base.spy_trend_ok()
    assert asked == ["SPY"], "the SPY shim must not follow the venue split"


def test_the_regime_read_is_cached_per_symbol(monkeypatch):
    """One cache keyed only by date would answer KOSPI with SPY's regime."""
    from TerraFin.analytics.analysis.patterns import _base

    values = {"SPY": [1.0] * 60 + [99.0], "^KS11": [99.0] * 60 + [1.0]}
    monkeypatch.setattr(_base, "_REGIME_CACHE", {})
    monkeypatch.setattr(_base, "closes", lambda df: values[df["symbol"]])

    fetched = []

    class _Factory:
        def get_market_data(self, symbol):
            fetched.append(symbol)
            return {"symbol": symbol}

    import TerraFin.data as tf_data

    monkeypatch.setattr(tf_data, "get_data_factory", lambda: _Factory())

    assert _base.index_trend_ok("SPY", 50) is True
    assert _base.index_trend_ok("^KS11", 50) is False
    # And served from the cache the second time, still not confused.
    assert _base.index_trend_ok("SPY", 50) is True
    # One fetch per symbol: asserting the values alone passes with no cache.
    assert fetched == ["SPY", "^KS11"]


def test_is_krx_ticker():
    assert is_krx_ticker("005930.KS")
    assert is_krx_ticker("038290.KQ")
    assert is_krx_ticker("005930")
    assert not is_krx_ticker("NVDA")
    assert not is_krx_ticker("BRK.B")
    assert not is_krx_ticker("")


# ── weekly RSI divergence ────────────────────────────────────────────────────


def test_weekly_rsi_delegates_with_weekly_bars_and_looser_bounds(monkeypatch):
    """The weekly pass must reuse the daily rule, on weekly bars, at 60/40.

    Weekly RSI(14) rarely reaches 30/70 — at 30 the bull side never fired on
    any real series tested — so the weekly call loosens the bounds while daily
    keeps the 70/30 that was asked for.
    """
    captured = {}

    def spy(ticker, ohlc, **kwargs):
        captured["ticker"] = ticker
        captured["rows"] = len(ohlc)
        captured.update(kwargs)
        return []

    monkeypatch.setattr(reversal, "_rsi_divergence", spy)
    daily = _frame(_ramp(100, 300, 600))
    reversal._weekly_rsi_divergence("AAA", daily)

    assert captured["rsi_high"] == 60.0
    assert captured["rsi_low"] == 40.0
    assert captured["name_prefix"] == "WEEKLY_"
    assert captured["severity"] == "high"
    # It was handed weekly bars, not the daily frame.
    assert captured["rows"] == len(weekly_bars(daily))
    assert captured["rows"] < len(daily)


def test_daily_rsi_keeps_its_own_thresholds():
    import inspect

    params = inspect.signature(reversal._rsi_divergence).parameters
    assert params["rsi_high"].default == 70.0
    assert params["rsi_low"].default == 30.0
    assert params["name_prefix"].default == ""
    assert params["severity"].default == "medium"


def test_weekly_signals_carry_the_data_week_for_dedup():
    """`week_ending` is what makes a weekly fire unique per week rather than
    per run day; without it the EOD scan falls back to the run date's ISO week,
    which double-counts on the KRX schedule."""
    fired = breakout._weekly_new_extreme("AAA", _frame(_ramp(100, 400, 700)))
    assert fired
    week = fired[0].snapshot["week_ending"]
    assert week and len(week) == 10  # ISO date

    # Identical across run days that share a completed week.
    closes = _ramp(100, 400, 700)
    weeks = {
        breakout._weekly_new_extreme("AAA", _frame(closes[: 700 - off]))[0].snapshot["week_ending"]
        for off in range(0, 3)
        if breakout._weekly_new_extreme("AAA", _frame(closes[: 700 - off]))
    }
    assert len(weeks) == 1, weeks


def test_flat_series_fires_nothing():
    flat = [100.0] * 700
    assert breakout._weekly_new_extreme("AAA", _frame(flat)) == []
    assert reversal._weekly_rsi_divergence("AAA", _frame(flat)) == []


def test_every_weekly_pattern_emits_week_ending():
    """The dedup key comes from `week_ending`; a weekly pattern that omits it
    silently falls back to the run date's ISO week, which double-ships on the
    KRX schedule and then swallows the next week."""
    advance = _frame(_ramp(100, 400, 700))
    decline = _frame(_ramp(400, 100, 700))

    for fired in (
        breakout._weekly_new_extreme("AAA", advance),
        breakout._weekly_new_extreme("AAA", decline),
    ):
        assert fired
        for signal in fired:
            assert signal.snapshot.get("week_ending"), signal.name


def test_weekly_rsi_snapshot_extra_reaches_the_signal(monkeypatch):
    """`_weekly_rsi_divergence` must inject `week_ending` into the snapshot.

    Asserted through the delegation contract because the divergence fire
    conditions are not reachable from a synthetic series.
    """
    captured = {}

    def spy(ticker, ohlc, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(reversal, "_rsi_divergence", spy)
    daily = _frame(_ramp(100, 300, 600))
    reversal._weekly_rsi_divergence("AAA", daily)

    extra = captured.get("snapshot_extra") or {}
    assert extra.get("week_ending") == weekly_bars(daily).index[-1].date().isoformat()


def _divergence_fixture(n: int = 49):
    """A damped sine on a rising drift, which produces the pivot pair the
    divergence rule needs. Fires at n=49; the fire window is narrow, so the
    length matters."""
    import math

    return [100 + 0.6 * i + 25 * (0.995**i) * math.sin(2 * math.pi * i / 20) for i in range(n)]


def test_rsi_divergence_emits_the_prefix_severity_and_snapshot_extra():
    """A real fire, not a spy: the prefix, severity and merged snapshot all
    have to survive to the emitted Signal."""
    fired = reversal._rsi_divergence(
        "AAA",
        _frame(_divergence_fixture()),
        rsi_high=60.0,
        rsi_low=40.0,
        name_prefix="WEEKLY_",
        severity="high",
        snapshot_extra={"week_ending": "2026-09-04"},
    )
    assert [x.name for x in fired] == ["WEEKLY_RSI_BEAR_DIVERGENCE"]
    assert fired[0].severity == "high"
    assert fired[0].snapshot["week_ending"] == "2026-09-04"
    # The rule's own fields survive the merge.
    assert "rsi_high" in fired[0].snapshot


def test_rsi_divergence_defaults_emit_no_prefix_and_medium():
    fired = reversal._rsi_divergence("AAA", _frame(_divergence_fixture()), rsi_high=60.0, rsi_low=40.0)
    assert [x.name for x in fired] == ["RSI_BEAR_DIVERGENCE"]
    assert fired[0].severity == "medium"
    assert "week_ending" not in fired[0].snapshot


def test_weekly_volume_dryup_carries_the_data_week():
    import numpy as np

    n, tail = 400, 25
    closes = list(np.linspace(100, 180, n))
    volumes = [1e6] * (n - tail) + [2.5e5] * tail
    idx = pd.date_range("2020-01-06", periods=n, freq="B")
    frame = pd.DataFrame(
        {"time": idx, "open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}
    ).set_index("time")

    metrics = breakout.detect_weekly_volume_dryup(frame, ticker="AAA")
    assert metrics and metrics["week_ending"]

    fired = breakout._weekly_volume_dryup_signal("AAA", frame)
    assert [x.name for x in fired] == ["WEEKLY_VOLUME_DRYUP"]
    assert fired[0].snapshot["week_ending"] == metrics["week_ending"]


# ── weekly MA crosses carry the data week ───────────────────────────────────


def test_bar_ma_cross_puts_the_supplied_week_in_its_snapshot():
    """Plumbing check with a short period, so a side flip is forceable.

    A natural weekly cross needs the final bar to be the first one across a
    20/60/120-week MA, which a synthetic ramp does not land on.
    """
    from TerraFin.analytics.analysis.patterns import trend

    # Below the 3-bar MA, then decisively above it on the last bar.
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 120.0]
    fired = trend._bar_ma_cross("AAA", _frame(closes), period=3, label="MA3W", horizon="week", week="2026-09-04")
    assert [s.name for s in fired] == ["MA3W_GOLDEN_CROSS"]
    assert fired[0].snapshot["week_ending"] == "2026-09-04"


def test_daily_ma_cross_omits_week_ending_entirely():
    from TerraFin.analytics.analysis.patterns import trend

    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 120.0]
    fired = trend._bar_ma_cross("AAA", _frame(closes), period=3, label="MA3", horizon="day")
    assert fired
    assert "week_ending" not in fired[0].snapshot


def test_ma_cross_grid_passes_the_data_week_to_the_weekly_leg(monkeypatch):
    """Guards the `week=` argument the grid must supply."""
    from TerraFin.analytics.analysis.patterns import trend

    seen = []

    def spy(ticker, ohlc, *, period, label, horizon, min_gap_pct=0.5, week=None):
        seen.append((label, horizon, week))
        return []

    monkeypatch.setattr(trend, "_bar_ma_cross", spy)
    daily = _frame(_ramp(100, 300, 900))
    trend._ma_cross_grid("AAA", daily)

    weekly_legs = [row for row in seen if row[1] == "week"]
    daily_legs = [row for row in seen if row[1] == "day"]
    assert weekly_legs, "grid ran no weekly leg"
    expected = weekly_bars(daily, "AAA").index[-1].date().isoformat()
    for _label, _horizon, week in weekly_legs:
        assert week == expected
    for _label, _horizon, week in daily_legs:
        assert week is None


def test_minervini_is_gated_on_the_names_own_venue(monkeypatch):
    """`_minervini_template` fires on a false→true transition of `_template_pass`.

    The earlier version of this test patched `passes_trend_template` (never
    called here) and a non-existent `_template_transition`, so the transition
    never happened and both sides came back empty — it could not fail.
    """
    from TerraFin.analytics.analysis.patterns import trend

    # cur=True on the full series, prev=False one bar back: the transition.
    monkeypatch.setattr(trend, "_template_pass", lambda cs: len(cs) % 2 == 0)
    # SPY down, KOSPI up: each name follows its own venue.
    monkeypatch.setattr(
        trend,
        "venue_trend_ok",
        lambda ticker, period=50: True if is_krx_ticker(ticker) else False,
    )

    closes = _ramp(100, 400, 700)
    frame = _frame(closes if len(closes) % 2 == 0 else closes[:-1])

    kr = trend._minervini_template("005930.KS", frame)
    us = trend._minervini_template("NVDA", frame)

    assert [x.name for x in kr] == ["MINERVINI_TEMPLATE"], "KR gated on a US index"
    assert us == [], "US name should stay suppressed while SPY is down"

    # And the KR name is suppressed when KOSPI itself is down.
    monkeypatch.setattr(trend, "venue_trend_ok", lambda ticker, period=50: False)
    assert trend._minervini_template("005930.KS", frame) == [], "KR not gated on KOSPI"


# ── holiday Friday ──────────────────────────────────────────────────────────


def test_holiday_friday_week_is_not_skipped():
    """KRX 2025-10-03 was a holiday Friday and the next week was closed for
    Chuseok, so the label-vs-last-date test called it partial on every run and
    that week's signals were lost outright."""
    from datetime import date

    from TerraFin.data.providers.market.sessions import is_session

    sessions = [d for d in pd.bdate_range("2025-01-01", "2025-10-31") if is_session(d.date(), "005930.KS")]
    closes = _ramp(100, 200, len(sessions))
    frame = pd.DataFrame(
        {
            "time": sessions,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1e6] * len(closes),
        }
    ).set_index("time")

    observed = set()
    for cut in range(len(sessions) // 2, len(sessions)):
        weekly = weekly_bars(frame.iloc[: cut + 1], "005930.KS")
        if len(weekly):
            observed.add(weekly.index[-1].date())

    assert date(2025, 10, 3) in observed
    assert date(2025, 10, 10) in observed


# ── the ticker must reach weekly_bars from every weekly entry point ──────────


def _krx_frame(start="2023-01-01", end="2025-10-31"):
    """KRX sessions only, long enough for the 52+10-week weekly detectors."""
    from TerraFin.data.providers.market.sessions import is_session

    sessions = [d for d in pd.bdate_range(start, end) if is_session(d.date(), "005930.KS")]
    closes = _ramp(100, 200, len(sessions))
    return pd.DataFrame(
        {
            "time": sessions,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1e6] * len(closes),
        }
    ).set_index("time")


def test_holiday_week_survives_end_to_end_through_a_detector():
    """Not just `weekly_bars` in isolation — through the detector.

    Drop the ticker at any call site and `last_session_on_or_before` judges a
    KRX frame against the NYSE calendar, so the 2025-10-03 holiday-Friday week
    is dropped again and its signals vanish.
    """
    from datetime import date

    frame = _krx_frame()
    weeks = set()
    for cut in range(len(frame) // 2, len(frame)):
        for signal in breakout._weekly_new_extreme("005930.KS", frame.iloc[: cut + 1]):
            weeks.add(signal.snapshot["week_ending"])

    assert date(2025, 10, 3).isoformat() in weeks
    assert date(2025, 10, 10).isoformat() in weeks


@pytest.mark.parametrize(
    "module_name, call",
    [
        ("breakout", lambda m: m._weekly_new_extreme("005930.KS", _krx_frame())),
        ("breakout", lambda m: m._weekly_volume_dryup_signal("005930.KS", _krx_frame())),
        ("breakout", lambda m: m.detect_weekly_volume_dryup(_krx_frame(), ticker="005930.KS")),
        ("reversal", lambda m: m._weekly_rsi_divergence("005930.KS", _krx_frame())),
        ("trend", lambda m: m._ma_cross_grid("005930.KS", _krx_frame())),
    ],
)
def test_every_weekly_entry_point_forwards_the_ticker(monkeypatch, module_name, call):
    """`weekly_bars` needs the ticker to pick the right session calendar."""
    from TerraFin.analytics.analysis.patterns import breakout, reversal, trend

    module = {"breakout": breakout, "reversal": reversal, "trend": trend}[module_name]
    seen = []
    real = weekly_bars

    def spy(ohlc, ticker=""):
        seen.append(ticker)
        return real(ohlc, ticker)

    monkeypatch.setattr(module, "weekly_bars", spy)
    call(module)

    assert seen, "weekly_bars was never called"
    assert all(t == "005930.KS" for t in seen), seen


def _bull_divergence_fixture(n: int = 48):
    """Mirror of `_divergence_fixture` tuned to fire the BULL branch.

    The two branches build their snapshots independently, so the bear fixture
    does not exercise the bull one.
    """
    import math

    return [max(1.0, 200 - 0.5 * i + 20 * (0.995**i) * math.sin(2 * math.pi * i / 16)) for i in range(n)]


def test_bull_branch_also_merges_snapshot_extra():
    fired = reversal._rsi_divergence(
        "AAA",
        _frame(_bull_divergence_fixture()),
        rsi_high=60.0,
        rsi_low=40.0,
        name_prefix="WEEKLY_",
        severity="high",
        snapshot_extra={"week_ending": "2026-09-04"},
    )
    assert [x.name for x in fired] == ["WEEKLY_RSI_BULL_DIVERGENCE"]
    assert fired[0].severity == "high"
    assert fired[0].snapshot["week_ending"] == "2026-09-04"
    assert "rsi_low" in fired[0].snapshot


def test_weekly_new_high_does_not_refire_while_the_close_ties_the_max():
    """`cs[-2] < high` must stay strict.

    With `<=` the anchor signal would re-fire every week a flat close ties the
    52-week maximum, instead of once on the transition.
    """
    from TerraFin.analytics.analysis.patterns._base import closes as _close_list

    rise = _ramp(100, 200, 600)
    fired_at, tied_at = [], []
    for extra_flat_weeks in range(0, 5):
        closes = rise + [200.0] * (extra_flat_weeks * 5)
        frame = _frame(closes)
        weekly = _close_list(weekly_bars(frame, "AAA"))
        names = [s.name for s in breakout._weekly_new_extreme("AAA", frame)]
        # A tie is when the previous weekly close already equals the max.
        if len(weekly) >= 2 and weekly[-2] == max(weekly[-52:]):
            tied_at.append(names)
        elif names:
            fired_at.append(names)

    assert fired_at, "the transition to a new high never fired"
    assert tied_at, "fixture produced no tie to check"
    assert all(names == [] for names in tied_at), tied_at


# ── the weekly detectors must be wired into evaluate() ──────────────────────


def test_evaluate_emits_the_weekly_breakout_and_rsi_families():
    """`eod_scan._evaluate_one` calls only `patterns.evaluate`.

    Drop either `extend` from a school's `evaluate` and the whole weekly
    feature unwires with every unit test still green.
    """
    from TerraFin.analytics.analysis.patterns import evaluate

    advance = _frame(_ramp(100, 400, 700))
    names = {s.name for s in evaluate("AAA", advance)}
    assert "WEEKLY_NEW_HIGH" in names

    # The reversal school is asserted separately, via the delegation tests
    # below — a natural weekly-RSI fire is not reachable from a ramp.


def test_evaluate_reaches_the_weekly_rsi_leg(monkeypatch):
    from TerraFin.analytics.analysis.patterns import evaluate, reversal

    called = []
    monkeypatch.setattr(reversal, "_weekly_rsi_divergence", lambda t, o: called.append(t) or [])
    evaluate("AAA", _frame(_ramp(100, 200, 400)))
    assert called == ["AAA"]


def test_evaluate_reaches_the_weekly_breakout_leg(monkeypatch):
    from TerraFin.analytics.analysis.patterns import breakout as bo
    from TerraFin.analytics.analysis.patterns import evaluate

    called = []
    monkeypatch.setattr(bo, "_weekly_new_extreme", lambda t, o: called.append(t) or [])
    evaluate("AAA", _frame(_ramp(100, 200, 400)))
    assert called == ["AAA"]


def test_weekly_new_low_does_not_refire_on_a_tie():
    """Mirror of the high-side tie guard."""
    from TerraFin.analytics.analysis.patterns._base import closes as _close_list

    decline = _ramp(400, 100, 600)
    fired_at, tied_at = [], []
    for extra in range(0, 5):
        closes = decline + [100.0] * (extra * 5)
        frame = _frame(closes)
        weekly = _close_list(weekly_bars(frame, "AAA"))
        names = [s.name for s in breakout._weekly_new_extreme("AAA", frame)]
        if len(weekly) >= 2 and weekly[-2] == min(weekly[-52:]):
            tied_at.append(names)
        elif names:
            fired_at.append(names)

    assert fired_at, "the transition to a new low never fired"
    assert tied_at, "fixture produced no tie to check"
    assert all(names == [] for names in tied_at), tied_at


def test_the_extreme_window_is_52_weeks_not_all_history():
    """A 52-week high below the all-time high must still fire."""
    # Peak, long decline well past a year, then a rally to a fresh 52-week high
    # that stays under the original peak.
    closes = _ramp(100, 400, 200) + _ramp(400, 150, 900) + _ramp(150, 300, 300)
    fired = breakout._weekly_new_extreme("AAA", _frame(closes))
    assert [s.name for s in fired] == ["WEEKLY_NEW_HIGH"]
    assert fired[0].snapshot["high"] < 400, "window reached past 52 weeks"


def test_the_trend_ma_needs_its_full_lookback():
    """At exactly `lookback` weekly bars there is no room for the 10-week MA."""
    # 52 weekly bars only.
    closes = _ramp(100, 200, 52 * 5)
    assert breakout._weekly_new_extreme("AAA", _frame(closes)) == []
    # With lookback + trend_sma + 1 weeks it may fire.
    longer = _ramp(100, 200, (52 + 10 + 2) * 5)
    assert breakout._weekly_new_extreme("AAA", _frame(longer))


def test_weekly_bars_survives_a_ticker_with_no_session_calendar():
    """`last_session_on_or_before` returns None for venues it does not know.

    Without the `final_session is None` guard this raises TypeError, which
    `_ma_cross_grid`'s narrow `except` would not catch.
    """
    from TerraFin.data.providers.market.sessions import last_session_on_or_before

    frame = _frame(_ramp(100, 200, 400))
    # Precondition: this venue really has no calendar answer, which is what
    # makes the None guard reachable.
    label = weekly_bars(frame).index[-1].date()
    assert last_session_on_or_before(label, "7203.T") is None
    assert len(weekly_bars(frame, "7203.T")) > 0
    from TerraFin.analytics.analysis.patterns import trend

    trend._ma_cross_grid("7203.T", frame)  # must not raise
