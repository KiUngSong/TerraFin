"""Tests for guru portfolio history (20-quarter) fetch, cache, and sparklines."""
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


# ─── _build_sparklines ────────────────────────────────────────────────────────

def test_build_sparklines_aligns_quarters():
    q0 = {"AAPL": _raw(100), "GOOG": _raw(50)}
    q1 = {"AAPL": _raw(120)}          # GOOG absent
    q2 = {"AAPL": _raw(110), "GOOG": _raw(60), "NVDA": _raw(30)}

    result = holdings._build_sparklines([q0, q1, q2])

    assert result["AAPL"] == [100, 120, 110]
    assert result["GOOG"] == [50, None, 60]
    assert result["NVDA"] == [None, None, 30]


def test_build_sparklines_empty_returns_empty():
    assert holdings._build_sparklines([]) == {}


def test_build_sparklines_single_quarter():
    q = {"MSFT": _raw(200)}
    result = holdings._build_sparklines([q])
    assert result == {"MSFT": [200]}


# ─── _format_rows with sparklines ────────────────────────────────────────────

def test_format_rows_with_sparklines_populates_history(monkeypatch):
    monkeypatch.setattr(holdings, "resolve_cusip_to_ticker", lambda c: None)
    sparklines = {"Apple": [100, 120, 110], "Google": [None, 50, 60]}
    rows = holdings._format_rows(
        current={"Apple": _raw(110), "Google": _raw(60)},
        previous=None,
        sparklines=sparklines,
    )
    apple = next(r for r in rows if r["Stock"] == "Apple")
    google = next(r for r in rows if r["Stock"] == "Google")
    assert apple["History"] == [100, 120, 110]
    assert google["History"] == [None, 50, 60]


def test_format_rows_without_sparklines_history_is_dash(monkeypatch):
    monkeypatch.setattr(holdings, "resolve_cusip_to_ticker", lambda c: None)
    rows = holdings._format_rows(
        current={"Apple": _raw(100)},
        previous=None,
        sparklines=None,
    )
    assert rows[0]["History"] == "-"


# ─── get_guru_holdings_history integration ───────────────────────────────────

def _make_filings_index(n: int) -> list[dict]:
    return [{"accession": f"acc{i}", "filing_date": f"2024-{12 - i:02d}-01"} for i in range(n)]


def test_get_guru_holdings_history_returns_newest_first(monkeypatch):
    from TerraFin.data.cache.manager import CacheManager

    monkeypatch.setattr(holdings, "GURU_CIK", _make_cik_registry())

    filings_index = _make_filings_index(3)

    def fake_read(namespace, key, ttl, **_):
        if key.endswith("__index"):
            return filings_index
        return None

    monkeypatch.setattr(CacheManager, "file_cache_read", staticmethod(fake_read))
    monkeypatch.setattr(CacheManager, "file_cache_write", staticmethod(lambda *a, **kw: None))

    def _fake_fetch_raw(cik, guru_name, accession, filing_date):
        shares_by_date = {
            "2024-12-01": {"AAPL": _raw(100)},
            "2024-11-01": {"AAPL": _raw(120)},
            "2024-10-01": {"AAPL": _raw(90)},
        }
        return shares_by_date.get(filing_date, {})

    monkeypatch.setattr(holdings, "_fetch_or_cached_raw", _fake_fetch_raw)

    result = holdings.get_guru_holdings_history("Test Guru")

    assert len(result) == 3
    # Newest first
    assert result[0]["filing_date"] == "2024-12-01"
    assert result[1]["filing_date"] == "2024-11-01"
    assert result[2]["filing_date"] == "2024-10-01"


def test_get_guru_holdings_history_sparkline_in_rows(monkeypatch):
    from TerraFin.data.cache.manager import CacheManager

    monkeypatch.setattr(holdings, "GURU_CIK", _make_cik_registry())

    filings_index = _make_filings_index(3)
    # Dates: 2024-12-01, 2024-11-01, 2024-10-01 (newest first in index)
    shares_by_date = {
        "2024-12-01": {"AAPL": _raw(100)},
        "2024-11-01": {"AAPL": _raw(120)},
        "2024-10-01": {"AAPL": _raw(90)},
    }

    def _fake_fetch_raw(cik, guru_name, accession, filing_date):
        return shares_by_date.get(filing_date, {})

    monkeypatch.setattr(holdings, "_fetch_or_cached_raw", _fake_fetch_raw)

    def fake_read(namespace, key, ttl, **_):
        if key.endswith("__index"):
            return filings_index
        return None

    monkeypatch.setattr(CacheManager, "file_cache_read", staticmethod(fake_read))
    monkeypatch.setattr(CacheManager, "file_cache_write", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(holdings, "resolve_cusip_to_ticker", lambda c: None)

    result = holdings.get_guru_holdings_history("Test Guru")

    # Latest filing rows should have sparkline oldest→newest: [90, 120, 100]
    latest_rows = result[0]["rows"]
    aapl_row = next(r for r in latest_rows if r["Stock"] == "AAPL")
    assert aapl_row["History"] == [90, 120, 100]


def test_get_guru_holdings_history_unknown_guru():
    with pytest.raises(ValueError, match="Unknown guru"):
        holdings.get_guru_holdings_history("Nonexistent Guru")


def test_get_guru_holdings_history_partial_failure_skips_filing(monkeypatch):
    from TerraFin.data.cache.manager import CacheManager

    monkeypatch.setattr(holdings, "GURU_CIK", _make_cik_registry())
    filings_index = _make_filings_index(2)

    def _fake_fetch_raw(cik, guru_name, accession, filing_date):
        if filing_date == "2024-12-01":
            raise ValueError("parse error")
        return {"GOOG": _raw(50)}

    monkeypatch.setattr(holdings, "_fetch_or_cached_raw", _fake_fetch_raw)

    def fake_read(namespace, key, ttl, **_):
        if key.endswith("__index"):
            return filings_index
        return None

    monkeypatch.setattr(CacheManager, "file_cache_read", staticmethod(fake_read))
    monkeypatch.setattr(CacheManager, "file_cache_write", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(holdings, "resolve_cusip_to_ticker", lambda c: None)

    result = holdings.get_guru_holdings_history("Test Guru")
    # Should still return 2 filings; erroring one gets empty rows
    assert len(result) == 2
    errored = next(r for r in result if r["filing_date"] == "2024-12-01")
    assert errored["rows"] == []


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
