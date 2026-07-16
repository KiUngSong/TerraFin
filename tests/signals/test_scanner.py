"""Tests for the alerting scanner."""
import pandas as pd
import pytest

from TerraFin.analytics.analysis.patterns import Signal


def _make_ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1_000_000] * len(closes),
    })


def test_scan_empty_watchlist(monkeypatch):
    import TerraFin.analytics.reports.scanner as sm

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return []

    monkeypatch.setattr(sm, "get_watchlist_service", lambda: _FakeSvc())
    assert sm.scan() == []


def test_scan_returns_signals_for_items(monkeypatch):
    import TerraFin.analytics.reports.scanner as sm

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": []}]

    monkeypatch.setattr(sm, "get_watchlist_service", lambda: _FakeSvc())
    monkeypatch.setattr(sm, "_fetch_ohlc", lambda ticker: _make_ohlc([100.0 + i * 2 for i in range(50)]))

    signals = sm.scan()
    assert isinstance(signals, list)
    assert all(s.ticker == "AAPL" for s in signals)


def test_scan_group_filter_passed(monkeypatch):
    import TerraFin.analytics.reports.scanner as sm

    seen_group = []

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            seen_group.append(group)
            return []

    monkeypatch.setattr(sm, "get_watchlist_service", lambda: _FakeSvc())
    sm.scan(group="tech")
    assert seen_group == ["tech"]


def test_scan_skips_erroring_tickers(monkeypatch):
    import TerraFin.analytics.reports.scanner as sm

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return [
                {"symbol": "ERR", "name": "Error", "move": "--", "tags": []},
                {"symbol": "OK", "name": "OK", "move": "+1%", "tags": []},
            ]

    def _fake_fetch(ticker):
        if ticker == "ERR":
            raise RuntimeError("network error")
        # An MA golden cross so the good ticker reliably produces a signal.
        return _make_ohlc([100.0] * 200 + [99.0, 101.0])

    monkeypatch.setattr(sm, "get_watchlist_service", lambda: _FakeSvc())
    monkeypatch.setattr(sm, "_fetch_ohlc", _fake_fetch)

    signals = sm.scan()
    tickers = {s.ticker for s in signals}
    assert "ERR" not in tickers
    assert any(s.ticker == "OK" for s in signals)
