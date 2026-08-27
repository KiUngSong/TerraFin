"""Tests for guru portfolio row formatting and the cached-index fast path."""
import pytest

from TerraFin.data.providers.corporate.filings.sec_edgar import holdings


@pytest.fixture(autouse=True)
def _reset_portfolio_payloads():
    from TerraFin.data.cache.registry import get_cache_manager

    manager = get_cache_manager()
    for source in list(manager._payload_specs):
        if source.startswith("portfolio."):
            manager.clear_payload(source)
            manager._payload_specs.pop(source, None)
    yield


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _raw(shares: int, value: int = 1000) -> dict:
    return {"value": value, "shares": shares, "cusips": set()}


def _make_cik_registry() -> dict:
    return {"Test Guru": 1234567}


# ─── _format_rows ────────────────────────────────────────────────────────────

def test_format_rows_history_is_dash(monkeypatch):
    monkeypatch.setattr(holdings, "resolve_cusip_to_ticker", lambda c: None)
    monkeypatch.setattr(holdings, "resolve_cusips_to_tickers", lambda cusips: {})
    rows = holdings._format_rows(
        current={"Apple": _raw(100)},
        previous=None,
    )
    assert rows[0]["History"] == "-"


# ─── get_guru_holdings ───────────────────────────────────────────────────────

def test_get_guru_holdings_fast_path_uses_cached_index(monkeypatch):
    """get_guru_holdings reuses history index cache and fetches only latest filing."""
    from TerraFin.data.cache.manager import CacheManager

    monkeypatch.setattr(holdings, "GURU_CIK", _make_cik_registry())
    monkeypatch.setattr(
        holdings,
        "_fetch_or_cached_raw",
        lambda cik, guru, acc, fd: {
            "AAPL_CUSIP": {"name": "Apple Inc", "shares": 100, "ticker": "AAPL", "value": 50000}
        },
    )

    def fake_read(namespace, key, ttl):
        if key.endswith("__index"):
            return [{"accession": "acc0", "filing_date": "2024-12-01"}]
        return None

    monkeypatch.setattr(CacheManager, "file_cache_read", fake_read)

    info, rows = holdings.get_guru_holdings("Test Guru")
    assert info["Period"] == "Q4 2024"
    assert rows[0]["Stock"].startswith("AAPL")


def test_get_guru_holdings_raises_when_no_filings(monkeypatch):
    """get_guru_holdings raises ValueError when EDGAR has no 13F for the guru."""
    from TerraFin.data.cache.manager import CacheManager

    monkeypatch.setattr(holdings, "GURU_CIK", _make_cik_registry())
    monkeypatch.setattr(CacheManager, "file_cache_read", lambda *a, **kw: None)
    monkeypatch.setattr(
        holdings,
        "_find_latest_13f",
        lambda cik, count=1: (_ for _ in ()).throw(ValueError("No 13F filing found for CIK 1234567")),
    )

    with pytest.raises(ValueError, match="No 13F filing found"):
        holdings.get_guru_holdings("Test Guru")
