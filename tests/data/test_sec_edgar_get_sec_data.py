import pandas as pd
import pytest

from TerraFin.data.cache import manager as cache_manager
from TerraFin.data.providers.corporate.filings import sec_edgar as sec_pkg
from TerraFin.data.providers.corporate.filings.sec_edgar import filing


@pytest.fixture(autouse=True)
def _isolated_file_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_manager, "_FILE_CACHE_DIR", tmp_path)
    # Reset the managed CIK/submissions/parsed caches so each test starts cold.
    filing.clear_sec_filings_cache()
    yield


def _install_fakes(monkeypatch, *, download_calls, parse_calls, html="<html>body</html>", parsed="parsed-md"):
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"AAPL": 320193})

    def fake_get_company_filings(cik, include_8k=False, include_history=False):
        return pd.DataFrame(
            {
                "form": ["10-Q"],
                "accessionNumber": ["0000320193-25-000001"],
                "primaryDocument": ["aapl-10q.htm"],
                "primaryDocDescription": ["10-Q"],
            }
        )

    def fake_download(cik, accession, file_name):
        download_calls.append((cik, accession, file_name))
        return html

    def fake_parse(html_content, filing_form, *, include_images=False):
        parse_calls.append((filing_form, include_images))
        return f"{parsed}|images={include_images}"

    monkeypatch.setattr(sec_pkg, "get_company_filings", fake_get_company_filings)
    monkeypatch.setattr(sec_pkg, "download_filing", fake_download)
    monkeypatch.setattr(sec_pkg, "parse_sec_filing", fake_parse)


def test_get_sec_data_caches_parsed_result(monkeypatch) -> None:
    downloads: list = []
    parses: list = []
    _install_fakes(monkeypatch, download_calls=downloads, parse_calls=parses)

    first = sec_pkg.get_sec_data("AAPL")
    second = sec_pkg.get_sec_data("AAPL")

    assert first.markdown == second.markdown
    assert first.ticker == "AAPL"
    assert len(downloads) == 1, "second call must skip download"
    assert len(parses) == 1, "second call must skip parse"


def test_get_sec_data_caches_per_include_images_flag(monkeypatch) -> None:
    downloads: list = []
    parses: list = []
    _install_fakes(monkeypatch, download_calls=downloads, parse_calls=parses)

    no_img = sec_pkg.get_sec_data("AAPL", include_images=False)
    with_img = sec_pkg.get_sec_data("AAPL", include_images=True)

    assert "images=False" in no_img.markdown
    assert "images=True" in with_img.markdown
    # Distinct cache entries → two fetches & two parses.
    assert len(downloads) == 2
    assert len(parses) == 2

    # But repeating the same flag is served from cache.
    sec_pkg.get_sec_data("AAPL", include_images=False)
    sec_pkg.get_sec_data("AAPL", include_images=True)
    assert len(downloads) == 2
    assert len(parses) == 2


def test_clear_sec_filings_cache_invalidates_parsed_output(monkeypatch) -> None:
    downloads: list = []
    parses: list = []
    _install_fakes(monkeypatch, download_calls=downloads, parse_calls=parses)

    sec_pkg.get_sec_data("AAPL")
    filing.clear_sec_filings_cache()
    sec_pkg.get_sec_data("AAPL")

    assert len(downloads) == 2, "clear must force a re-download on the next call"
    assert len(parses) == 2


def test_get_sec_data_raises_for_unknown_ticker(monkeypatch) -> None:
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"AAPL": 320193})

    with pytest.raises(ValueError, match="CIK not found"):
        sec_pkg.get_sec_data("BOGUS")


def test_clear_sec_filings_cache_also_resets_in_memory_ticker_memo(monkeypatch) -> None:
    """Coherence check: after clearing, the next CIK lookup must go back through
    the (now empty) file cache rather than silently serving the stale dict."""
    fetches: list[str] = []

    def fake_fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict:
        fetches.append(url)
        return {"data": [["AAPL", 320193]], "fields": ["ticker", "cik"]}

    monkeypatch.setattr(filing, "_fetch_json", fake_fetch_json)

    filing.get_ticker_to_cik_dict_cached()
    assert len(fetches) == 1

    filing.clear_sec_filings_cache()
    filing.get_ticker_to_cik_dict_cached()
    assert len(fetches) == 2, "clear must invalidate both file cache and in-memory memo"


def test_get_sec_toc_default_is_top_level_only(monkeypatch) -> None:
    """Default max_level=2: agents see the Part list, not every sub-item."""
    downloads: list = []
    parses: list = []
    _install_fakes(
        monkeypatch,
        download_calls=downloads,
        parse_calls=parses,
        parsed="## PART I\n\n### Item 1\n\nbody\n\n### Item 2\n",
    )

    toc = sec_pkg.get_sec_toc("AAPL")

    assert [(e.level, e.title) for e in toc] == [(2, "PART I")]
    assert all(e.id and e.anchor for e in toc)

    # Follow-up get_sec_data with the same flags hits the cache get_sec_toc populated.
    sec_pkg.get_sec_data("AAPL")
    assert len(downloads) == 1
    assert len(parses) == 1


def test_get_sec_toc_full_hierarchy_when_max_level_none(monkeypatch) -> None:
    downloads: list = []
    parses: list = []
    _install_fakes(
        monkeypatch,
        download_calls=downloads,
        parse_calls=parses,
        parsed="## PART I\n\n### Item 1\n\n### Item 2\n",
    )

    toc = sec_pkg.get_sec_toc("AAPL", max_level=None)

    assert [(e.level, e.title) for e in toc] == [
        (2, "PART I"),
        (3, "Item 1"),
        (3, "Item 2"),
    ]
