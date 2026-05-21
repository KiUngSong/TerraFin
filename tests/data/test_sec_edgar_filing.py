from pathlib import Path

import pytest

from TerraFin.data.cache import manager as cache_manager
from TerraFin.data.providers.corporate.filings.sec_edgar import filing


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_NVDA_INDEX_HTML = _FIXTURES_DIR / "sample_8k_index_NVDA_0001045810-26-000051.html"
_NVDA_EX99_HTML = _FIXTURES_DIR / "sample_ex99_NVDA_2026-05-20.html"


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


def test_parse_accession_index_html_extracts_ex99_rows() -> None:
    """The NVDA 2026-05-20 8-K accession lists EX-99.1 (q1fy27pr.htm) and
    EX-99.2 (q1fy27cfocommentary.htm). The parser must surface both with
    their type classification intact — filenames don't start with `ex-99`
    so the type column is the only reliable signal."""
    html = _NVDA_INDEX_HTML.read_text()
    rows = filing._parse_accession_index_html(html)
    by_type = {r["type"]: r for r in rows}
    assert "EX-99.1" in by_type
    assert by_type["EX-99.1"]["document"] == "q1fy27pr.htm"
    assert by_type["EX-99.2"]["document"] == "q1fy27cfocommentary.htm"
    # Primary 8-K is also in the same table.
    assert "8-K" in by_type
    assert by_type["8-K"]["document"] == "nvda-20260520.htm"


def test_filter_ex99_html_exhibits_keeps_only_html_ex99() -> None:
    files = [
        {"seq": "1", "description": "8-K", "document": "nvda.htm", "type": "8-K", "size": "1"},
        {"seq": "2", "description": "", "document": "pr.htm", "type": "EX-99.1", "size": "1"},
        {"seq": "3", "description": "", "document": "comm.htm", "type": "EX-99.2", "size": "1"},
        {"seq": "4", "description": "", "document": "graphic.jpg", "type": "EX-99.3", "size": "1"},
        {"seq": "5", "description": "", "document": "audit.pdf", "type": "EX-99.4", "size": "1"},
    ]
    kept = filing.filter_ex99_html_exhibits(files)
    assert [r["document"] for r in kept] == ["pr.htm", "comm.htm"]


def test_list_filing_files_returns_exhibits_for_nvda(monkeypatch) -> None:
    """End-to-end: list_filing_files hits the (faked) index.html and yields
    the EX-99.1 / EX-99.2 rows. Caches: second call must skip the fetch."""
    calls: list[str] = []
    html = _NVDA_INDEX_HTML.read_text()

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        calls.append(url)
        return html

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    rows = filing.list_filing_files(1045810, "000104581026000051")
    types = {r["type"] for r in rows}
    assert {"EX-99.1", "EX-99.2", "8-K"}.issubset(types)

    rows_again = filing.list_filing_files(1045810, "000104581026000051")
    assert rows == rows_again
    assert len(calls) == 1, "second call must be served from file cache"


def test_list_filing_files_url_uses_padded_cik_and_hyphenated_accession(monkeypatch) -> None:
    """Spot-check URL construction: CIK is zero-padded to 10 digits, the
    accession-prefixed `<dashed>-index.html` page is the target."""
    captured: list[str] = []
    html = _NVDA_INDEX_HTML.read_text()

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        captured.append(url)
        return html

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)
    filing.list_filing_files(1045810, "000104581026000051")
    assert captured == [
        "https://www.sec.gov/Archives/edgar/data/0001045810/000104581026000051/"
        "0001045810-26-000051-index.html"
    ]


def test_download_exhibit_round_trip_and_caches(monkeypatch) -> None:
    calls: list[str] = []
    content = _NVDA_EX99_HTML.read_text()

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        calls.append(url)
        return content

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    first = filing.download_exhibit(1045810, "000104581026000051", "q1fy27pr.htm")
    second = filing.download_exhibit(1045810, "000104581026000051", "q1fy27pr.htm")
    assert first == content
    assert first == second
    assert len(calls) == 1, "second exhibit fetch must hit the file cache"


@pytest.mark.parametrize(
    "accession",
    ["0001045810-26-000051", "000104581026000051"],
)
def test_accession_index_url_normalizes_dashed_and_undashed_inputs(accession) -> None:
    """``_accession_index_url`` must accept either the dashed
    (``0001045810-26-000051``) or undashed (``000104581026000051``)
    accession form and produce the same EDGAR URL. The dashed form
    breaks the path-slicing ``[:10]/[10:12]/[12:]`` math unless
    normalized at the function top."""
    expected = (
        "https://www.sec.gov/Archives/edgar/data/0001045810/000104581026000051/"
        "0001045810-26-000051-index.html"
    )
    assert filing._accession_index_url(1045810, accession) == expected


def test_filter_ex99_html_exhibits_excludes_ex99_cert_certification() -> None:
    """``EX-99-CERT`` is an investment-company certification exhibit shape
    (no ``.<digit>`` suffix). The current EX-99.x regex anchors on
    ``EX-99(.\\d+)?$``, so an ``EX-99-CERT`` row must NOT slip through
    even though it shares the ``EX-99`` prefix. Synthesized — the NVDA
    8-K accession we use elsewhere doesn't contain a CERT row."""
    files = [
        {"seq": "1", "description": "PR", "document": "pr.htm", "type": "EX-99.1", "size": "1"},
        {"seq": "2", "description": "Cert", "document": "cert.htm", "type": "EX-99-CERT", "size": "1"},
        {"seq": "3", "description": "Other", "document": "other.htm", "type": "EX-99-CERTNYI", "size": "1"},
    ]
    kept = filing.filter_ex99_html_exhibits(files)
    kept_types = [r["type"] for r in kept]
    assert kept_types == ["EX-99.1"], kept_types


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
