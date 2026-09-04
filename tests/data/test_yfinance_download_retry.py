import pandas as pd
import pytest

import TerraFin.data.providers.market.yfinance as yfinance_module


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [10]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-02")], name="Date"),
    )


@pytest.fixture(autouse=True)
def _clean_streak():
    yfinance_module.reset_empty_streak()
    yield
    yfinance_module.reset_empty_streak()


def test_isolated_empty_still_probes_and_reports_invalid(monkeypatch) -> None:
    """One bad symbol among healthy ones must keep the precise verdict."""
    probes = []
    monkeypatch.setattr(yfinance_module.yf, "download", lambda t, **k: pd.DataFrame())
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda t: probes.append(t) or False)

    with pytest.raises(ValueError, match="Invalid ticker: NOPE"):
        yfinance_module._download_frame("NOPE", period="max")

    assert probes == ["NOPE"], "exactly one probe, not one per attempt"


def test_streak_of_empties_stops_probing_and_reports_transient(monkeypatch) -> None:
    """Throttling: after the limit, stop spending a request to confirm it."""
    probes = []
    monkeypatch.setattr(yfinance_module.yf, "download", lambda t, **k: pd.DataFrame())
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda t: probes.append(t) or False)

    limit = yfinance_module._EMPTY_STREAK_PROBE_LIMIT
    for i in range(limit - 1):
        with pytest.raises(ValueError):
            yfinance_module._download_frame(f"T{i}", period="max")
    assert len(probes) == limit - 1

    with pytest.raises(yfinance_module.TransientMarketDataError, match="throttling"):
        yfinance_module._download_frame("TLAST", period="max")
    assert len(probes) == limit - 1, "no probe once the circuit is open"


def test_a_success_resets_the_streak(monkeypatch) -> None:
    state = {"empty": True}
    monkeypatch.setattr(
        yfinance_module.yf, "download",
        lambda t, **k: pd.DataFrame() if state["empty"] else _frame(),
    )
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda t: False)

    for i in range(yfinance_module._EMPTY_STREAK_PROBE_LIMIT - 1):
        with pytest.raises(ValueError):
            yfinance_module._download_frame(f"T{i}", period="max")

    state["empty"] = False
    assert not yfinance_module._download_frame("GOOD", period="max").empty

    state["empty"] = True
    with pytest.raises(ValueError):
        yfinance_module._download_frame("AFTER", period="max")


def test_valid_ticker_wraps_upstream_error_as_transient(monkeypatch) -> None:
    class _Boom:
        def __init__(self, _t):
            pass

        def history(self, **_kwargs):
            raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr(yfinance_module.yf, "Ticker", _Boom)

    with pytest.raises(yfinance_module.TransientMarketDataError, match="validity probe failed"):
        yfinance_module.valid_ticker("MMM")


def test_transient_probe_failure_is_not_reported_as_invalid_ticker(monkeypatch) -> None:
    monkeypatch.setattr(yfinance_module.yf, "download", lambda t, **k: pd.DataFrame())

    def boom(_ticker):
        raise yfinance_module.TransientMarketDataError("probe failed")

    monkeypatch.setattr(yfinance_module, "valid_ticker", boom)

    with pytest.raises(yfinance_module.TransientMarketDataError):
        yfinance_module._download_frame("MMM", period="max")


def test_download_is_called_exactly_once_per_fetch(monkeypatch) -> None:
    """No retry-on-empty: retrying only multiplies requests at a rate limiter."""
    calls = []
    monkeypatch.setattr(
        yfinance_module.yf, "download", lambda t, **k: calls.append(t) or pd.DataFrame()
    )
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda t: False)

    with pytest.raises(ValueError):
        yfinance_module._download_frame("X", period="max")

    assert len(calls) == 1


def _hist_stub(index, closes, cols=("Close",)):
    import pandas as pd
    return pd.DataFrame(dict.fromkeys(cols, closes), index=pd.to_datetime(index))


def test_a_history_window_holds_the_download_lock(monkeypatch):
    """Ticker.history() writes yfinance's shared globals on its error path, so
    it takes the same lock as yf.download — `valid_ticker` already does. This
    one is called from top_movers' 8-way fan-out, where the sibling threads are
    inside the factory holding it."""
    import yfinance as yf

    from TerraFin.data.providers.market import yfinance as prov

    held = {}

    class _Tk:
        def __init__(self, _t):
            held["locked"] = prov._YF_DOWNLOAD_LOCK.locked()

        def history(self, **k):
            return _hist_stub(["2026-08-28", "2026-08-31"], [1.0, 2.0])

    monkeypatch.setattr(yf, "Ticker", _Tk)
    prov.get_history_window("MRVL", "2026-08-01", "2026-09-01")
    assert held["locked"] is True


def test_a_history_window_drops_null_closes(monkeypatch):
    """A null-close row is a session with no price. Left in, it becomes a NaN
    change_pct that the caller's `is not None` filter waves through."""
    import yfinance as yf

    from TerraFin.data.providers.market import yfinance as prov

    class _Tk:
        def __init__(self, _t):
            pass

        def history(self, **k):
            return _hist_stub(["2026-08-27", "2026-08-28", "2026-08-31"],
                              [1.0, float("nan"), 2.0])

    monkeypatch.setattr(yf, "Ticker", _Tk)
    out = prov.get_history_window("QCOM", "2026-08-01", "2026-09-01")
    assert list(out["time"]) == ["2026-08-27", "2026-08-31"]
    assert list(out["close"]) == [1.0, 2.0]


def test_a_history_window_returns_an_empty_frame_not_a_raise(monkeypatch):
    """The caller has no guard of its own for a bad ticker; an exception here
    would skip its CNBC fallback entirely."""
    import yfinance as yf

    from TerraFin.data.providers.market import yfinance as prov

    class _Boom:
        def __init__(self, _t):
            pass

        def history(self, **k):
            raise RuntimeError("upstream said no")

    monkeypatch.setattr(yf, "Ticker", _Boom)
    out = prov.get_history_window("NOPE", "2026-08-01", "2026-09-01")
    assert list(out.columns) == ["time", "close"] and out.empty


def test_a_permanent_gap_warns_once_per_process(caplog):
    """These holes never get filled, and this runs on every chunk build
    including cache hits. Warning each time buries the line that matters."""
    import logging

    import pandas as pd

    from TerraFin.data.providers.market import yfinance as prov

    prov._SEEN_GAPS.clear()
    idx = pd.to_datetime(["2026-08-26", "2026-08-27", "2026-08-31"])
    frame = pd.DataFrame({"Close": [1.0, 2.0, 3.0], "Volume": [1, 1, 1]}, index=idx)
    with caplog.at_level(logging.WARNING, logger=prov.log.name):
        for _ in range(3):
            prov._history_chunk_from_frame(
                frame, ticker="QCOM", period="1m", has_older=False,
                is_complete=True, source_version="test",
            )
    assert sum("missing 1 session" in r.message for r in caplog.records) == 1


def test_one_hole_shared_across_tickers_warns_once(caplog):
    """A hole belongs to the calendar-vs-feed pair, not the ticker: over the
    real cache one hole-set is shared by 197 KRX names and another by 70 US
    ones. Keyed per ticker that is 267 lines describing two facts."""
    import logging

    import pandas as pd

    from TerraFin.data.providers.market import yfinance as prov

    prov._SEEN_GAPS.clear()
    idx = pd.to_datetime(["2026-08-26", "2026-08-27", "2026-08-31"])
    frame = pd.DataFrame({"Close": [1.0, 2.0, 3.0], "Volume": [1, 1, 1]}, index=idx)
    with caplog.at_level(logging.WARNING, logger=prov.log.name):
        for tk in ("QCOM", "JNJ", "LLY", "PFE"):
            prov._history_chunk_from_frame(
                frame, ticker=tk, period="1m", has_older=False,
                is_complete=True, source_version="test",
            )
    assert sum("missing 1 session" in r.message for r in caplog.records) == 1


def test_the_gap_log_cache_is_bounded():
    """`_SEEN_GAPS` is module-level with no eviction, on a live server path.
    `missing_sessions` runs on every chunk build, and a rolling `period="3y"`
    window advances its lower bound daily — so holes scroll out and each ticker
    yields a fresh tuple about once a day. That is the tickers-x-days growth
    `sessions._all_sessions` rejects for itself one file away."""
    from TerraFin.data.providers.market import yfinance as prov

    prov._SEEN_GAPS.clear()
    try:
        for i in range(prov._SEEN_GAPS_MAX + 50):
            assert prov._note_gap((f"2026-01-{i:04d}",)) is True
        assert len(prov._SEEN_GAPS) <= prov._SEEN_GAPS_MAX
    finally:
        prov._SEEN_GAPS.clear()


def test_eviction_is_fifo_not_a_wipe():
    """Clearing wholesale would re-log every live hole at once — the flood the
    rate limit exists to stop. The oldest entry goes; the newest stay."""
    from TerraFin.data.providers.market import yfinance as prov

    prov._SEEN_GAPS.clear()
    try:
        for i in range(prov._SEEN_GAPS_MAX):
            prov._note_gap((f"seed-{i}",))
        newest = next(reversed(prov._SEEN_GAPS))
        prov._note_gap(("overflow",))
        assert ("seed-0",) not in prov._SEEN_GAPS, "the oldest entry is evicted"
        assert newest in prov._SEEN_GAPS, "recent entries survive"
        assert prov._note_gap(("overflow",)) is False, "still rate-limited"
    finally:
        prov._SEEN_GAPS.clear()


def test_the_gap_log_mutation_is_serialised(monkeypatch):
    """`_history_chunk_from_frame` runs outside `_YF_DOWNLOAD_LOCK` and the
    cached-artifact path never takes it, so `_note_gap` is reached by two
    fan-outs at once (top_movers' 8 workers, market_data's 12). Unsynchronised,
    eviction at the cap raises `RuntimeError: dictionary changed size during
    iteration` or a `KeyError` on the double pop — and that escapes
    `get_recent_history(force_refresh=True)` into `_pinned_frame`'s except,
    dropping the caller onto the raw yfinance branch.

    Asserted structurally, not by racing: under the GIL the window is too small
    to hit reliably, and a test that fails one run in fifty is worse than none.
    """
    import threading

    from TerraFin.data.providers.market import yfinance as prov

    held = []

    class _Probe:
        def __init__(self):
            self._lock = threading.Lock()

        def __enter__(self):
            self._lock.acquire()
            held.append("in")
            return self

        def __exit__(self, *exc):
            held.append("out")
            self._lock.release()
            return False

    monkeypatch.setattr(prov, "_SEEN_GAPS_LOCK", _Probe())
    prov._SEEN_GAPS.clear()
    try:
        for i in range(prov._SEEN_GAPS_MAX + 5):
            prov._note_gap((f"g-{i}",))
        assert held, "the mutation must happen under the lock"
        assert held == ["in", "out"] * (prov._SEEN_GAPS_MAX + 5), \
            "every call, including the evicting ones, must take it"
        assert len(prov._SEEN_GAPS) <= prov._SEEN_GAPS_MAX
    finally:
        prov._SEEN_GAPS.clear()


def test_the_gap_log_survives_concurrent_callers():
    """`_history_chunk_from_frame` runs outside `_YF_DOWNLOAD_LOCK` and the
    cached-artifact path never takes it, so `_note_gap` is reached by two
    fan-outs at once (top_movers' 8 workers, market_data's 12).

    Unsynchronised, eviction at the cap raises `RuntimeError: dictionary changed
    size during iteration` or a `KeyError` on the double pop — and that escapes
    `get_recent_history(force_refresh=True)` into `_pinned_frame`'s except,
    dropping the caller onto the raw yfinance branch."""
    from concurrent.futures import ThreadPoolExecutor

    from TerraFin.data.providers.market import yfinance as prov

    prov._SEEN_GAPS.clear()
    try:
        # Start at the cap so every call takes the eviction branch.
        for i in range(prov._SEEN_GAPS_MAX):
            prov._note_gap((f"seed-{i}",))
        errors = []

        def hammer(n):
            try:
                for j in range(60):
                    prov._note_gap((f"t{n}-{j}",))
            except Exception as exc:          # noqa: BLE001 — the point of the test
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(hammer, range(12)))
        assert not errors, f"concurrent eviction raised: {errors[:3]}"
        assert len(prov._SEEN_GAPS) <= prov._SEEN_GAPS_MAX
    finally:
        prov._SEEN_GAPS.clear()


def test_the_history_window_pins_the_adjustment_basis(monkeypatch):
    """`auto_adjust=False` puts these closes on a different basis than
    `_download_frame`'s inside one mover ranking — a published-number risk the
    line's own comment names, and flipping it passed both suites."""
    from TerraFin.data.providers.market import yfinance as prov

    seen = {}

    class _Tk:
        def __init__(self, t):
            pass

        def history(self, *a, **k):
            seen.update(k)
            return pd.DataFrame({"Close": [1.0, 2.0]},
                                index=pd.to_datetime(["2026-08-28", "2026-08-31"]))

    monkeypatch.setattr(prov.yf, "Ticker", _Tk)
    prov.get_history_window("NVDA", "2026-08-01", "2026-09-01")
    assert seen.get("auto_adjust") is True, \
        "the window must match _download_frame's basis"


def test_a_null_close_row_does_not_count_as_a_present_session(caplog, monkeypatch):
    """The hole detector judges the dates carrying a usable close. Dropping the
    `notna` filter makes a null-close row read as present, so the only hole
    signal the data layer emits misses the holes it exists for.

    2026-08-28 is an NYSE session; with a null close it is a hole, and the
    warning is where that reaches anyone. `chunk is not None` asserted nothing —
    `_history_chunk_from_frame` returns one unconditionally."""
    import logging

    from TerraFin.data.providers.market import yfinance as prov

    monkeypatch.setattr(prov, "_SEEN_GAPS", {})   # the log is once-per-process
    frame = pd.DataFrame(
        {"Close": [1.0, None, 3.0]},
        index=pd.to_datetime(["2026-08-27", "2026-08-28", "2026-08-31"]))
    with caplog.at_level(logging.WARNING, logger=prov.log.name):
        chunk = prov._history_chunk_from_frame(
            frame, ticker="NVDA", period="1m", has_older=False,
            is_complete=True, source_version="t")
    assert chunk is not None
    assert "2026-08-28" in caplog.text, \
        "a null-close row must be reported as a missing session, not counted present"
