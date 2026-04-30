"""Runtime validation for data contracts."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from TerraFin.data.contracts import (
    CalendarEvent,
    EventList,
    FilingDocument,
    FinancialStatementFrame,
    IndicatorSnapshot,
    TOCEntry,
)


def test_toc_entry_valid():
    e = TOCEntry(id="a", title="Item 1", level=0, anchor="item-1")
    assert e.level == 0


def test_toc_entry_negative_level_rejected():
    with pytest.raises(ValueError):
        TOCEntry(id="a", title="x", level=-1, anchor="x")


def test_filing_document_valid():
    doc = FilingDocument(
        ticker="AAPL",
        filing_type="10-K",
        accession="0000320193-24-000123",
        filing_date="2024-01-15",
        markdown="# hello",
        toc=[],
    )
    assert doc.ticker == "AAPL"


def test_filing_document_invalid_filing_type():
    with pytest.raises(ValueError):
        FilingDocument(
            ticker="AAPL",
            filing_type="invalid",  # type: ignore[arg-type]
            accession="x",
            filing_date="2024-01-15",
            markdown="",
            toc=[],
        )


def test_filing_document_invalid_filing_date():
    with pytest.raises(ValueError):
        FilingDocument(
            ticker="AAPL",
            filing_type="10-K",
            accession="x",
            filing_date="not-a-date",
            markdown="",
            toc=[],
        )


def test_filing_document_empty_accession_rejected():
    with pytest.raises(ValueError):
        FilingDocument(
            ticker="AAPL",
            filing_type="10-K",
            accession="",
            filing_date="2024-01-15",
            markdown="",
            toc=[],
        )


def test_filing_document_make_empty():
    doc = FilingDocument.make_empty("AAPL", "10-K")
    assert doc.ticker == "AAPL"
    assert doc.accession == ""


def test_calendar_event_valid():
    ev = CalendarEvent(
        id="1",
        title="x",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        category="macro",
        importance="low",
        display_time="",
    )
    assert ev.id == "1"


def test_calendar_event_naive_datetime_rejected():
    with pytest.raises(ValueError):
        CalendarEvent(
            id="1",
            title="x",
            start=datetime(2026, 1, 1),
            category="macro",
            importance="low",
            display_time="",
        )


def test_calendar_event_invalid_category():
    with pytest.raises(ValueError):
        CalendarEvent(
            id="1",
            title="x",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            category="invalid",  # type: ignore[arg-type]
            importance="low",
            display_time="",
        )


def test_calendar_event_invalid_importance():
    with pytest.raises(ValueError):
        CalendarEvent(
            id="1",
            title="x",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            category="macro",
            importance="invalid",  # type: ignore[arg-type]
            display_time="",
        )


def test_event_list_make_empty():
    el = EventList.make_empty()
    assert len(el) == 0


def test_event_list_non_list_rejected():
    with pytest.raises(ValueError):
        EventList(events="not a list")  # type: ignore[arg-type]


def test_financial_statement_frame_valid_dates():
    df = pd.DataFrame({"2024-01-01": [1.0], "2023-01-01": [2.0]}, index=["revenue"])
    fsf = FinancialStatementFrame(df, statement_type="income", period="annual", ticker="AAPL")
    assert fsf.ticker == "AAPL"


def test_financial_statement_frame_non_date_columns_rejected():
    df = pd.DataFrame({"not_a_date": [1.0]}, index=["revenue"])
    with pytest.raises(ValueError):
        FinancialStatementFrame(df, statement_type="income", period="annual", ticker="AAPL")


def test_indicator_snapshot_make_empty():
    snap = IndicatorSnapshot.make_empty()
    assert snap.name == ""
    assert snap.as_of == ""
