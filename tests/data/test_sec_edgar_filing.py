import pytest

from TerraFin.data.cache import manager as cache_manager
from TerraFin.data.providers.corporate.filings.sec_edgar import filing


@pytest.fixture(autouse=True)
def _isolated_file_cache(tmp_path, monkeypatch):
    """Redirect the shared file cache to a tmp dir so tests don't touch ~/.terrafin."""
    monkeypatch.setattr(cache_manager, "_FILE_CACHE_DIR", tmp_path)
    filing.clear_sec_index_cache()
    yield


def test_sec_user_agent_requires_explicit_env_var(monkeypatch) -> None:
    monkeypatch.delenv("TERRAFIN_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")

    with pytest.raises(filing.SecEdgarConfigurationError, match="TERRAFIN_SEC_USER_AGENT"):
        filing._sec_user_agent()


def test_sec_user_agent_supports_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("TERRAFIN_SEC_USER_AGENT", "Acme Research sec-contact@acme.test")

    assert filing._sec_user_agent() == "Acme Research sec-contact@acme.test"


def test_create_sec_client_prefers_explicit_user_agent_override(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []

    class _FakeSECClient:
        def __init__(self, user_agent: str, host_url: str) -> None:
            captured.append((user_agent, host_url))

    monkeypatch.setenv("TERRAFIN_SEC_USER_AGENT", "My TerraFin Bot bot@example.com")
    monkeypatch.setattr(filing, "SECClient", _FakeSECClient)

    _ = filing.create_sec_client(host_url="www.sec.gov")

    assert captured == [("My TerraFin Bot bot@example.com", "www.sec.gov")]


def test_sec_edgar_status_reports_disabled_when_user_agent_missing(monkeypatch) -> None:
    monkeypatch.delenv("TERRAFIN_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")

    assert filing.sec_edgar_is_configured() is False
    assert "TERRAFIN_SEC_USER_AGENT" in filing.sec_edgar_status_message()


def test_sec_edgar_module_has_no_free_proxy_fallback() -> None:
    assert not hasattr(filing, "get_free_proxy")


def test_sec_edgar_module_exposes_no_legacy_ttlcache() -> None:
    # The 60s in-memory TTLCache was removed; everything now goes through the
    # shared CacheManager file cache under `sec_filings`.
    assert not hasattr(filing, "cache")


def test_try_cik_request_caches_parsed_payload(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        calls.append(url)
        return {"data": [["AAPL", 320193]], "fields": ["ticker", "cik"]}

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    first = filing._try_cik_request()
    second = filing._try_cik_request()

    assert first == {"data": [["AAPL", 320193]], "fields": ["ticker", "cik"]}
    assert first == second
    assert calls == [filing.CIK_URL], "second call must be served from file cache"


def test_get_company_filings_filters_by_form(monkeypatch) -> None:
    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        return {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K", "DEF 14A"],
                    "accessionNumber": ["a1", "a2", "a3", "a4"],
                    "filingDate": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"],
                },
                "files": [],
            }
        }

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    df = filing.get_company_filings(123)
    assert sorted(df["form"].tolist()) == ["10-K", "10-Q"]

    df_8k = filing.get_company_filings(123, include_8k=True)
    assert sorted(df_8k["form"].tolist()) == ["10-K", "10-Q", "8-K"]


def test_get_company_filings_paginates_history_when_requested(monkeypatch) -> None:
    recent = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["recent-a"],
                "filingDate": ["2025-01-01"],
            },
            "files": [{"name": "CIK0000000123-submissions-001.json"}],
        }
    }
    history = {
        "form": ["10-Q", "10-K"],
        "accessionNumber": ["old-a", "old-b"],
        "filingDate": ["2010-01-01", "2009-01-01"],
    }

    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        if url.endswith("submissions-001.json"):
            return history
        return recent

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    df_default = filing.get_company_filings(123)
    assert df_default["accessionNumber"].tolist() == ["recent-a"], "default must skip history"

    df_full = filing.get_company_filings(123, include_history=True)
    assert set(df_full["accessionNumber"]) == {"recent-a", "old-a", "old-b"}


def test_get_company_filings_returns_none_for_missing_cik() -> None:
    assert filing.get_company_filings(None) is None


def test_submissions_file_cache_survives_across_calls(monkeypatch) -> None:
    """Second `get_company_filings` for the same CIK must hit the file cache."""
    calls: list[str] = []

    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        calls.append(url)
        return {
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "accessionNumber": ["a1"],
                    "filingDate": ["2025-01-01"],
                },
                "files": [],
            }
        }

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    filing.get_company_filings(42)
    filing.get_company_filings(42)

    assert len(calls) == 1, "second call must be served from file cache, not refetched"


def test_clear_sec_filings_cache_drops_cik_mapping(monkeypatch) -> None:
    """After clear_sec_filings_cache, _try_cik_request must refetch from upstream."""
    call_count = {"n": 0}

    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        call_count["n"] += 1
        return {"data": [["AAPL", 320193]], "fields": ["ticker", "cik"]}

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    filing._try_cik_request()
    filing._try_cik_request()
    assert call_count["n"] == 1, "baseline: second call should be cached"

    filing.clear_sec_filings_cache()
    filing._try_cik_request()
    assert call_count["n"] == 2, "after clear, the next call must refetch"


def test_download_filing_is_not_cached(monkeypatch) -> None:
    """Raw HTML is transient — each call re-fetches regardless of repetition."""
    calls: list[str] = []

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        calls.append(url)
        return "<html>body</html>"

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    filing.download_filing(42, "acc123", "doc.htm")
    filing.download_filing(42, "acc123", "doc.htm")

    assert len(calls) == 2, "raw HTML downloads must not be file-cached"
