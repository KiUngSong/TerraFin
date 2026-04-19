"""Tests for the three SEC-filing capabilities wired into the agent runtime."""

import pytest

from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.service import TerraFinAgentService
from TerraFin.agent.tool_contracts import HOSTED_TOOL_CONTRACTS
from TerraFin.interface.stock import payloads


@pytest.fixture(autouse=True)
def _stub_payloads(monkeypatch):
    """Intercept network-facing payload builders with deterministic stubs."""
    monkeypatch.setattr(payloads, "get_ticker_to_cik_dict_cached", lambda: {"AAPL": 320193})

    def fake_filings_df(cik, include_8k=False):
        import pandas as pd

        return pd.DataFrame(
            {
                "form": ["10-K", "10-Q", "8-K"],
                "accessionNumber": ["0000320193-25-000001", "0000320193-24-000010", "0000320193-24-000007"],
                "filingDate": ["2025-02-02", "2024-11-02", "2024-08-02"],
                "reportDate": ["2024-12-28", "2024-09-28", "2024-08-01"],
                "primaryDocument": ["aapl-20241228.htm", "aapl-20240928.htm", "aapl-8k.htm"],
                "primaryDocDescription": ["10-K", "10-Q", "8-K"],
            }
        )

    monkeypatch.setattr(payloads, "get_company_filings", fake_filings_df)
    monkeypatch.setattr(payloads, "download_filing", lambda cik, acc, doc: "<html>irrelevant</html>")
    fake_md = (
        "## PART I - FINANCIAL INFORMATION\n\n"
        "## Item 1. Business\n\n"
        "Apple designs, manufactures, and markets smartphones.\n"
        "Revenue grew 5% year over year driven by services growth.\n\n"
        "## Item 7. MD&A\n\n"
        "Liquidity remained strong with operating cash flow of $110B.\n"
    )
    monkeypatch.setattr(payloads, "parse_sec_filing", lambda html, form, *, include_images=False: fake_md)


def test_capability_registry_exposes_three_sec_tools() -> None:
    registry = build_default_capability_registry()
    names = registry.names()
    for expected in ("sec_filings", "sec_filing_document", "sec_filing_section"):
        assert expected in names, f"{expected} should be registered"


def test_tool_contracts_registered_for_every_sec_capability() -> None:
    for expected in ("sec_filings", "sec_filing_document", "sec_filing_section"):
        assert expected in HOSTED_TOOL_CONTRACTS, f"{expected} missing a tool contract"


def test_sec_filings_returns_list_with_edgar_links() -> None:
    svc = TerraFinAgentService()
    result = svc.sec_filings("AAPL")

    assert result["ticker"] == "AAPL"
    assert result["cik"] == 320193
    assert len(result["filings"]) == 3
    assert all("documentUrl" in f and "indexUrl" in f for f in result["filings"])
    # iXBRL viewer wrapper lands on the primary document.
    assert "sec.gov/ix?doc=" in result["filings"][0]["documentUrl"]
    assert result["processing"]["sourceVersion"] == "sec-filings-list"


def test_sec_filing_document_returns_toc_without_markdown() -> None:
    svc = TerraFinAgentService()
    result = svc.sec_filing_document(
        "AAPL",
        accession="0000320193-25-000001",
        primaryDocument="aapl-20241228.htm",
        form="10-K",
    )

    assert "markdown" not in result, "document-level tool must NOT return the full body"
    assert [e["text"] for e in result["toc"]] == [
        "PART I - FINANCIAL INFORMATION",
        "Item 1. Business",
        "Item 7. MD&A",
    ]
    assert result["charCount"] > 0
    assert result["processing"]["sourceVersion"] == "sec-filing-document"


def test_sec_filing_section_returns_only_target_section_body() -> None:
    svc = TerraFinAgentService()
    result = svc.sec_filing_section(
        "AAPL",
        accession="0000320193-25-000001",
        primaryDocument="aapl-20241228.htm",
        sectionSlug="item-1-business",
        form="10-K",
    )

    assert result["sectionSlug"] == "item-1-business"
    assert result["sectionTitle"] == "Item 1. Business"
    assert "Apple designs" in result["markdown"]
    # MUST stop at the next heading — Item 7 prose must not leak in.
    assert "Liquidity" not in result["markdown"]
    assert result["charCount"] == len(result["markdown"])


def test_sec_filing_section_raises_lookup_error_for_unknown_slug() -> None:
    svc = TerraFinAgentService()
    with pytest.raises(LookupError, match="not found"):
        svc.sec_filing_section(
            "AAPL",
            accession="0000320193-25-000001",
            primaryDocument="aapl-20241228.htm",
            sectionSlug="does-not-exist",
            form="10-K",
        )


def test_sec_filing_section_error_includes_retry_hint_and_full_slug_list() -> None:
    """The error message must give the LLM everything it needs to retry
    without giving up: explicit 'do NOT report not exist', the 5 largest
    slugs with sizes (as a size-based fallback when name matching fails),
    and the full slug list. Otherwise the agent reads 'not found' as a
    dead end and tells the user the section doesn't exist — which is
    exactly the failure mode this fix targets."""
    svc = TerraFinAgentService()
    try:
        svc.sec_filing_section(
            "AAPL",
            accession="0000320193-25-000001",
            primaryDocument="aapl-20241228.htm",
            sectionSlug="financial-statements",  # agent's common guess
            form="10-K",
        )
    except LookupError as exc:
        msg = str(exc)
    else:
        raise AssertionError("Expected LookupError for unknown slug.")

    # Retry directive — the LLM must not treat this as a dead end.
    assert "Do NOT report" in msg or "retry" in msg.lower()
    # 5-largest hint — this is how the agent recovers when Item 7 / Item 8
    # aren't in the TOC under their expected names.
    assert "largest" in msg.lower() or "chars" in msg
    # Full slug list so the agent can self-correct without a second TOC fetch.
    assert "part-i" in msg
    assert "item-1-business" in msg


def test_sec_filing_section_stops_at_raw_toc_entry_not_next_content_heading() -> None:
    """Body bounds come from the TOC's own lineIndex list — no scanning markdown
    for heading-looking text, which would false-match inline `##` tokens."""
    svc = TerraFinAgentService()
    # Item 1 Business → next toc entry is Item 7 MD&A; Liquidity section must be absent.
    result = svc.sec_filing_section(
        "AAPL",
        accession="0000320193-25-000001",
        primaryDocument="aapl-20241228.htm",
        sectionSlug="item-1-business",
        form="10-K",
    )
    assert "Revenue grew 5%" in result["markdown"]
    assert "operating cash flow" not in result["markdown"]
