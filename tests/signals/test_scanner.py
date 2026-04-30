"""Tests for the alerting scanner."""
import pandas as pd
import pytest

from TerraFin.signals.alerting.conditions import Signal


def _make_ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def test_scan_empty_watchlist(monkeypatch):
    from TerraFin.signals.alerting import scanner as scanner_mod

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return []

    monkeypatch.setattr(scanner_mod, "get_watchlist_service", lambda: _FakeSvc())
    from TerraFin.signals.alerting.scanner import scan

    result = scan()
    assert result == []


def test_scan_returns_signals_for_items(monkeypatch):
    from TerraFin.signals.alerting import scanner as scanner_mod
    import TerraFin.signals.alerting.scanner as sm

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return [{"symbol": "AAPL", "name": "Apple", "move": "+1%", "tags": []}]

    rises = [100.0 + i * 2 for i in range(50)]
    monkeypatch.setattr(scanner_mod, "get_watchlist_service", lambda: _FakeSvc())
    monkeypatch.setattr(sm, "_fetch_ohlc", lambda ticker: _make_ohlc(rises))

    from TerraFin.signals.alerting.scanner import scan

    signals = scan()
    assert isinstance(signals, list)
    assert all(s.ticker == "AAPL" for s in signals)


def test_scan_group_filter_passed(monkeypatch):
    from TerraFin.signals.alerting import scanner as scanner_mod
    import TerraFin.signals.alerting.scanner as sm

    seen_group = []

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            seen_group.append(group)
            return []

    monkeypatch.setattr(scanner_mod, "get_watchlist_service", lambda: _FakeSvc())
    from TerraFin.signals.alerting.scanner import scan

    scan(group="tech")
    assert seen_group == ["tech"]


def test_scan_skips_erroring_tickers(monkeypatch):
    from TerraFin.signals.alerting import scanner as scanner_mod
    import TerraFin.signals.alerting.scanner as sm

    class _FakeSvc:
        def get_watchlist_snapshot(self, group=None):
            return [
                {"symbol": "ERR", "name": "Error", "move": "--", "tags": []},
                {"symbol": "OK", "name": "OK", "move": "+1%", "tags": []},
            ]

    def _fake_fetch(ticker):
        if ticker == "ERR":
            raise RuntimeError("network error")
        return _make_ohlc([100.0 + i * 2 for i in range(50)])

    monkeypatch.setattr(scanner_mod, "get_watchlist_service", lambda: _FakeSvc())
    monkeypatch.setattr(sm, "_fetch_ohlc", _fake_fetch)

    from TerraFin.signals.alerting.scanner import scan

    signals = scan()
    tickers = {s.ticker for s in signals}
    assert "ERR" not in tickers
