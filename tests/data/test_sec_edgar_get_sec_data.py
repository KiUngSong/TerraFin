from pathlib import Path

import pandas as pd
import pytest

from TerraFin.data.cache import manager as cache_manager
from TerraFin.data.providers.corporate.filings import sec_edgar as sec_pkg
from TerraFin.data.providers.corporate.filings.sec_edgar import filing


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_NVDA_8K_HTML = _FIXTURES_DIR / "sample_8k_NVDA_0001045810-26-000051.html"
_NVDA_INDEX_HTML = _FIXTURES_DIR / "sample_8k_index_NVDA_0001045810-26-000051.html"
_NVDA_EX99_HTML = _FIXTURES_DIR / "sample_ex99_NVDA_2026-05-20.html"


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


def test_get_sec_data_8k_appends_ex99_exhibits(monkeypatch) -> None:
    """End-to-end-ish: real NVDA 8-K body + real index.html + real EX-99.1 PR
    (all loaded from fixtures, network mocked at `_fetch_text`). The cached
    markdown must include both the 8-K item heading(s) AND an exhibit heading."""
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"NVDA": 1045810})

    def fake_get_company_filings(cik, include_8k=False, include_history=False):
        return pd.DataFrame(
            {
                "form": ["8-K"],
                "accessionNumber": ["0001045810-26-000051"],
                "primaryDocument": ["nvda-20260520.htm"],
                "primaryDocDescription": ["8-K"],
                "filingDate": ["2026-05-20"],
            }
        )

    monkeypatch.setattr(sec_pkg, "get_company_filings", fake_get_company_filings)

    body_html = _NVDA_8K_HTML.read_text()
    index_html = _NVDA_INDEX_HTML.read_text()
    ex99_html = _NVDA_EX99_HTML.read_text()

    fetched: list[str] = []

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        fetched.append(url)
        if url.endswith("-index.html"):
            return index_html
        if url.endswith("nvda-20260520.htm"):
            return body_html
        if url.endswith("q1fy27pr.htm") or url.endswith("q1fy27cfocommentary.htm"):
            return ex99_html
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    doc = sec_pkg.get_sec_data("NVDA", filing_type="8-K")

    assert "## Item " in doc.markdown, "primary 8-K item heading missing"
    assert "## Exhibit 99.1" in doc.markdown, "EX-99.1 exhibit heading missing"
    # And the slug surfaces in the TOC.
    slugs = [e.id for e in doc.toc]
    # `_slugify` strips the dot in `99.1`, so the slug is `exhibit-991-...`.
    assert any(s.startswith("exhibit-991") for s in slugs), slugs


def test_get_sec_data_8k_survives_missing_accession_index(monkeypatch) -> None:
    """If the accession-index fetch 404s, the orchestrator still returns the
    parsed primary 8-K body — just without exhibits."""
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"NVDA": 1045810})
    monkeypatch.setattr(
        sec_pkg,
        "get_company_filings",
        lambda *a, **k: pd.DataFrame(
            {
                "form": ["8-K"],
                "accessionNumber": ["0001045810-26-000051"],
                "primaryDocument": ["nvda-20260520.htm"],
                "primaryDocDescription": ["8-K"],
                "filingDate": ["2026-05-20"],
            }
        ),
    )

    body_html = _NVDA_8K_HTML.read_text()

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        if url.endswith("-index.html"):
            raise filing.SecEdgarUnavailableError("simulated 404")
        if url.endswith("nvda-20260520.htm"):
            return body_html
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    doc = sec_pkg.get_sec_data("NVDA", filing_type="8-K")
    assert "## Item " in doc.markdown
    assert "## Exhibit" not in doc.markdown


def test_get_sec_data_8k_marks_unreachable_exhibit(monkeypatch) -> None:
    """If the index resolves but a specific exhibit 404s, the orchestrator
    emits a ``(fetch failed)`` marker so the caller knows it existed."""
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"NVDA": 1045810})
    monkeypatch.setattr(
        sec_pkg,
        "get_company_filings",
        lambda *a, **k: pd.DataFrame(
            {
                "form": ["8-K"],
                "accessionNumber": ["0001045810-26-000051"],
                "primaryDocument": ["nvda-20260520.htm"],
                "primaryDocDescription": ["8-K"],
                "filingDate": ["2026-05-20"],
            }
        ),
    )

    body_html = _NVDA_8K_HTML.read_text()
    index_html = _NVDA_INDEX_HTML.read_text()

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        if url.endswith("-index.html"):
            return index_html
        if url.endswith("nvda-20260520.htm"):
            return body_html
        # Every exhibit fetch fails.
        raise filing.SecEdgarUnavailableError("simulated 404")

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    doc = sec_pkg.get_sec_data("NVDA", filing_type="8-K")
    assert "(fetch failed)" in doc.markdown
    assert "## Exhibit 99.1" in doc.markdown


def test_get_sec_data_8k_renders_heading_less_exhibit_body(monkeypatch) -> None:
    """Some issuers ship EX-99.1 press releases as a single ``<p>`` blob
    with no internal headings (e.g. a one-paragraph dividend notice).
    The 8-K orchestrator must still wrap it under a ``## Exhibit 99.1
    — Press Release`` heading and preserve the body text — heading
    promotion in the orchestrator is what guarantees the exhibit shows
    up in the TOC regardless of how the issuer structured the body."""
    monkeypatch.setattr(sec_pkg, "get_ticker_to_cik_dict_cached", lambda: {"NVDA": 1045810})
    monkeypatch.setattr(
        sec_pkg,
        "get_company_filings",
        lambda *a, **k: pd.DataFrame(
            {
                "form": ["8-K"],
                "accessionNumber": ["0001045810-26-000051"],
                "primaryDocument": ["nvda-20260520.htm"],
                "primaryDocDescription": ["8-K"],
                "filingDate": ["2026-05-20"],
            }
        ),
    )

    body_html = _NVDA_8K_HTML.read_text()
    # Minimal accession index containing one EX-99.1 row only — simpler
    # than the full NVDA fixture so we can assert exactly one Exhibit heading.
    index_html = (
        "<html><body>"
        '<table summary="Document Format Files"><tr>'
        "<td>1</td><td>8-K</td><td><a>nvda-20260520.htm</a></td><td>8-K</td><td>1</td>"
        "</tr><tr>"
        "<td>2</td><td>EX-99.1</td><td><a>plain.htm</a></td><td>EX-99.1</td><td>1</td>"
        "</tr></table></body></html>"
    )
    # Exhibit body with NO <h*> tags whatsoever.
    plain_ex99 = (
        "<html><body>"
        "<p>NVIDIA Corporation today declared a quarterly cash dividend "
        "of $0.01 per share payable June 27, 2026.</p>"
        "</body></html>"
    )

    def fake_fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
        if url.endswith("-index.html"):
            return index_html
        if url.endswith("nvda-20260520.htm"):
            return body_html
        if url.endswith("plain.htm"):
            return plain_ex99
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(filing, "_fetch_text", fake_fetch_text)

    doc = sec_pkg.get_sec_data("NVDA", filing_type="8-K")
    # The orchestrator-emitted heading is present even though the body had no <h*>.
    assert "## Exhibit 99.1 — Press Release" in doc.markdown
    # Body text survives intact under that heading.
    assert "quarterly cash dividend" in doc.markdown


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
