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
