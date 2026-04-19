import pandas as pd
import pytest
from fastapi import HTTPException

from TerraFin.interface.stock import payloads


def _stub_filings_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "form": ["10-K", "10-Q", "10-Q/A", "8-K", "DEF 14A"],
            "accessionNumber": ["0000320193-25-000001", "0000320193-24-000010", "0000320193-24-000008", "0000320193-24-000007", "0000320193-24-000006"],
            "filingDate": ["2025-02-02", "2024-11-02", "2024-08-10", "2024-08-02", "2024-05-01"],
            "reportDate": ["2024-12-28", "2024-09-28", "2024-06-28", "2024-08-01", ""],
            "primaryDocument": ["aapl-20241228.htm", "aapl-20240928.htm", "aapl-20240628a.htm", "aapl-8k.htm", "def14a.htm"],
            "primaryDocDescription": ["10-K", "10-Q", "10-Q/A", "8-K", "DEF 14A"],
        }
    )


@pytest.fixture
def cik_mapping(monkeypatch):
    monkeypatch.setattr(payloads, "get_ticker_to_cik_dict_cached", lambda: {"AAPL": 320193})


def test_build_filings_list_payload_returns_filings_with_edgar_links(monkeypatch, cik_mapping) -> None:
    monkeypatch.setattr(payloads, "get_company_filings", lambda cik, include_8k=False: _stub_filings_df())

    result = payloads.build_filings_list_payload("AAPL")

    assert result["ticker"] == "AAPL"
    assert result["cik"] == 320193
    assert len(result["filings"]) == 5
    # Newest-first ordering preserved.
    assert result["filings"][0]["filingDate"] == "2025-02-02"
    # documentUrl uses SEC's inline-XBRL viewer so the click opens the rendered
    # filing (styled, navigable) rather than the raw HTML. indexUrl still points
    # at the directory for debugging / file-level access.
    first = result["filings"][0]
    assert first["indexUrl"] == "https://www.sec.gov/Archives/edgar/data/0000320193/000032019325000001/"
    assert first["documentUrl"] == (
        "https://www.sec.gov/ix?doc=/Archives/edgar/data/0000320193/000032019325000001/aapl-20241228.htm"
    )


def test_build_filings_list_payload_prioritizes_forms_for_frontend_dropdown(monkeypatch, cik_mapping) -> None:
    monkeypatch.setattr(payloads, "get_company_filings", lambda cik, include_8k=False: _stub_filings_df())

    result = payloads.build_filings_list_payload("AAPL")

    # Frontend dropdown gets 10-K first, 10-Q next, amendments grouped with parent
    # priority, other forms at the end. Amendment appears after its parent form.
    assert result["forms"][:4] == ["10-K", "10-Q", "10-Q/A", "8-K"]
    assert "DEF 14A" in result["forms"]


def test_build_filings_list_payload_surfaces_latestByForm_even_when_buried(monkeypatch, cik_mapping) -> None:
    """Agents otherwise scan the flat list and give up when 8-Ks cluster on top.
    Verify `latestByForm` offers a direct lookup regardless of chronological order."""
    import pandas as pd

    # 8-Ks cluster on top in chronological order — 10-K is position 2, 10-Q position 3.
    eight_k_heavy = pd.DataFrame(
        {
            "form": ["8-K", "8-K", "10-K", "8-K", "10-Q"],
            "accessionNumber": ["a1", "a2", "a3", "a4", "a5"],
            "filingDate": ["2026-04-10", "2026-04-02", "2026-02-05", "2026-02-04", "2025-10-30"],
            "reportDate": ["2026-04-07", "2026-03-30", "2025-12-31", "2026-02-04", "2025-09-30"],
            "primaryDocument": ["a1.htm", "a2.htm", "a3.htm", "a4.htm", "a5.htm"],
            "primaryDocDescription": ["8-K", "8-K", "10-K", "8-K", "10-Q"],
        }
    )
    monkeypatch.setattr(payloads, "get_company_filings", lambda cik, include_8k=False: eight_k_heavy)

    result = payloads.build_filings_list_payload("AAPL")

    latest = result["latestByForm"]
    assert latest["10-K"]["accession"] == "a3"
    assert latest["10-K"]["primaryDocument"] == "a3.htm"
    assert latest["10-Q"]["accession"] == "a5"
    assert latest["8-K"]["accession"] == "a1", "latestByForm must pick the newest 8-K (a1), not some other one"


def test_build_filings_list_payload_raises_for_unknown_ticker(monkeypatch) -> None:
    monkeypatch.setattr(payloads, "get_ticker_to_cik_dict_cached", lambda: {})

    with pytest.raises(HTTPException) as exc:
        payloads.build_filings_list_payload("BOGUS")
    assert exc.value.status_code == 404


def test_build_filings_list_payload_handles_empty_upstream(monkeypatch, cik_mapping) -> None:
    monkeypatch.setattr(payloads, "get_company_filings", lambda cik, include_8k=False: pd.DataFrame())

    result = payloads.build_filings_list_payload("AAPL")
    assert result["filings"] == []
    assert result["forms"] == []


def test_build_filing_document_payload_returns_markdown_and_camelcase_toc(monkeypatch, cik_mapping) -> None:
    monkeypatch.setattr(payloads, "download_filing", lambda cik, acc, doc: "<html>ignored</html>")

    fake_md = "## PART I\n\nbody\n\n## PART II\n"
    monkeypatch.setattr(payloads, "parse_sec_filing", lambda html, form, *, include_images=False: fake_md)

    result = payloads.build_filing_document_payload(
        "AAPL",
        accession="0000320193-25-000001",
        primary_document="aapl-20241228.htm",
        form="10-K",
    )

    assert result["ticker"] == "AAPL"
    assert result["accession"] == "000032019325000001"
    assert result["markdown"] == fake_md
    assert result["charCount"] == len(fake_md)
    # Every TOC entry must expose camelCase keys consistent with the rest of the API.
    assert all({"level", "text", "lineIndex", "slug", "charCount"}.issubset(e) for e in result["toc"])
    assert [e["text"] for e in result["toc"]] == ["PART I", "PART II"]
    # documentUrl opens the iXBRL viewer, not the raw archive path.
    assert result["documentUrl"].startswith("https://www.sec.gov/ix?doc=/Archives/edgar/data/")
    assert result["documentUrl"].endswith("aapl-20241228.htm")


def test_build_filing_document_payload_requires_primary_document(monkeypatch, cik_mapping) -> None:
    with pytest.raises(HTTPException) as exc:
        payloads.build_filing_document_payload("AAPL", accession="0000320193-25-000001", primary_document="")
    assert exc.value.status_code == 400


def test_build_filing_document_payload_propagates_unsupported_form_as_422(monkeypatch, cik_mapping) -> None:
    monkeypatch.setattr(payloads, "download_filing", lambda cik, acc, doc: "<html></html>")

    def bad_parse(*_args, **_kwargs):
        raise ValueError("Filing form 'DEF 14A' not supported.")

    monkeypatch.setattr(payloads, "parse_sec_filing", bad_parse)

    with pytest.raises(HTTPException) as exc:
        payloads.build_filing_document_payload(
            "AAPL",
            accession="0000320193-25-000001",
            primary_document="def14a.htm",
            form="DEF 14A",
        )
    assert exc.value.status_code == 422
