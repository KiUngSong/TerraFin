"""Coverage for the null-payload guards in stock payload builders.

When yfinance is fed a non-ticker string (e.g. a 13F issuer name like
"ISHARES INC"), it tends to return a thin truthy dict rather than raise.
The guards convert that into a 404 so the agent's repair layer triggers.
"""

import pytest
from fastapi import HTTPException

from TerraFin.interface.stock import payloads


def test_build_company_info_payload_raises_on_all_null_core_fields(monkeypatch) -> None:
    monkeypatch.setattr(payloads, "get_ticker_info", lambda _: {"trailingPegRatio": None})

    with pytest.raises(HTTPException) as exc_info:
        payloads.build_company_info_payload("ISHARES INC")

    assert exc_info.value.status_code == 404
    assert "No data found for ticker" in exc_info.value.detail


def test_build_company_info_payload_returns_payload_for_real_ticker(monkeypatch) -> None:
    monkeypatch.setattr(
        payloads,
        "get_ticker_info",
        lambda _: {
            "shortName": "Apple Inc.",
            "marketCap": 3_000_000_000_000,
            "currentPrice": 200.0,
            "previousClose": 198.0,
            "sector": "Technology",
        },
    )

    payload = payloads.build_company_info_payload("AAPL")

    assert payload["ticker"] == "AAPL"
    assert payload["shortName"] == "Apple Inc."
    assert payload["changePercent"] == pytest.approx(((200.0 / 198.0) - 1.0) * 100.0, rel=1e-3)


def test_build_earnings_payload_raises_on_empty_records(monkeypatch) -> None:
    monkeypatch.setattr(payloads, "get_ticker_earnings", lambda _: [])

    with pytest.raises(HTTPException) as exc_info:
        payloads.build_earnings_payload("UNKNOWN")

    assert exc_info.value.status_code == 404
    assert "No data found for ticker" in exc_info.value.detail
