"""Tests for the `pattern_scan` cross-sectional sweep capability."""

import pandas as pd
import pytest

from TerraFin.agent.service import TerraFinAgentService
from TerraFin.analytics.analysis.patterns import Signal
from TerraFin.analytics.reports import scanner


@pytest.fixture(autouse=True)
def _stub_scan_inputs(monkeypatch):
    """Replace the per-symbol price fetch and pattern evaluation with stubs.

    `pattern_scan` is a fan-out over network fetches, so the unit under test
    here is the symbol resolution, severity filtering, and payload shape.
    """

    monkeypatch.setattr(scanner, "_fetch_ohlc", lambda ticker, period="1y": pd.DataFrame({"close": [1.0, 2.0]}))

    def fake_evaluate(ticker: str, _ohlc) -> list[Signal]:
        # Only "medium" and "high" occur in the real catalogue — no pattern
        # emits "low", so a stub must not invent one.
        return [
            Signal(name="MA20_GOLDEN_CROSS", ticker=ticker, severity="medium", message="stub medium"),
            Signal(name="RSI_BEAR_DIVERGENCE", ticker=ticker, severity="medium", message="stub medium 2"),
            Signal(name="52W_NEW_HIGH", ticker=ticker, severity="high", message="stub high"),
        ]

    monkeypatch.setattr(scanner, "evaluate", fake_evaluate)


@pytest.fixture()
def service() -> TerraFinAgentService:
    return TerraFinAgentService()


def test_pattern_scan_accepts_a_comma_separated_string(service) -> None:
    payload = service.pattern_scan(tickers="nvda, amd")

    assert payload["scanned"] == 2
    assert payload["matched"] == 6
    assert payload["failed"] == 0
    assert {signal["ticker"] for signal in payload["signals"]} == {"NVDA", "AMD"}
    assert payload["processing"]["sourceVersion"] == "pattern-scan"


def test_pattern_scan_accepts_a_list_and_uppercases_symbols(service) -> None:
    payload = service.pattern_scan(tickers=["nvda"])

    assert payload["scanned"] == 1
    assert {signal["ticker"] for signal in payload["signals"]} == {"NVDA"}


def test_pattern_scan_filters_by_minimum_severity(service) -> None:
    high_only = service.pattern_scan(tickers="NVDA,AMD", severity_min="high")

    assert high_only["scanned"] == 2, "severity filtering must not change reported coverage"
    assert high_only["matched"] == 2
    assert {signal["severity"] for signal in high_only["signals"]} == {"high"}

    medium_up = service.pattern_scan(tickers="NVDA,AMD", severity_min="medium")
    assert {signal["severity"] for signal in medium_up["signals"]} == {"medium", "high"}

    low = service.pattern_scan(tickers="NVDA,AMD", severity_min="low")
    assert low["matched"] == medium_up["matched"], "no pattern emits 'low', so low == medium"


def test_pattern_scan_rejects_an_unknown_severity(service) -> None:
    with pytest.raises(ValueError, match="severity_min"):
        service.pattern_scan(tickers="NVDA", severity_min="critical")


def test_pattern_scan_falls_back_to_the_watchlist(service, monkeypatch) -> None:
    """With no `tickers`, the watchlist supplies the symbol set and the count."""

    import TerraFin.agent.service.service as service_module

    monkeypatch.setattr(
        service_module,
        "get_watchlist_service",
        lambda: type("_Svc", (), {"get_watchlist_snapshot": lambda self, group=None: [{"symbol": "TSLA"}]})(),
    )

    payload = service.pattern_scan()

    assert payload["scanned"] == 1
    assert {signal["ticker"] for signal in payload["signals"]} == {"TSLA"}


def test_pattern_scan_returns_empty_payload_for_no_symbols(service) -> None:
    payload = service.pattern_scan(tickers="")

    assert payload["scanned"] == 0
    assert payload["matched"] == 0
    assert payload["signals"] == []


def test_scanner_tickers_argument_bypasses_the_watchlist(monkeypatch) -> None:
    """The scanner must not touch the watchlist service when given tickers."""

    def explode():
        raise AssertionError("watchlist service must not be consulted")

    monkeypatch.setattr(scanner, "get_watchlist_service", explode)

    signals = scanner.scan(tickers=["nvda", "  ", "amd"])

    assert {signal.ticker for signal in signals} == {"NVDA", "AMD"}
