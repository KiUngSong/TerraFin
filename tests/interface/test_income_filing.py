"""Coverage for the SEC-filing income-statement / cash-flow parser.

These are the deterministic table parsers behind the income Sankey's yfinance
fallback. Each test drives a synthetic 10-Q markdown (no network) that reproduces
a real structural hazard the parser has to survive:

  - a table-of-contents decoy above the real statement, whose unit note sits out
    of a naive fixed window (a thousands-reporting filer, → 1000x error);
  - opex split into non-standard line items the classifier can't name, so total
    operating expense has to be anchored on reported operating income to balance;
  - a statement with no cost-of-revenue line at all (must fail over, not guess);
  - a cash-flow statement with both quarterly and period-to-date columns (must
    pick the YTD one), a thousands unit, and a Q3 nine-month span.
"""

import pytest

from TerraFin.interface.pages.stock import income_filing


def _patch(monkeypatch, markdown: str, report_date: str = "2026-06-30") -> None:
    monkeypatch.setattr(income_filing, "build_filings_list_payload",
                        lambda _t: {"latestByForm": {"10-Q": {
                            "accession": "0000000000-26-000001",
                            "primaryDocument": "q.htm", "reportDate": report_date}}})
    monkeypatch.setattr(income_filing, "build_filing_document_payload",
                        lambda *a, **k: {"markdown": markdown})


# A thousands-reporting filer with a TOC decoy above the real heading. The real
# statement carries "(in thousands)" a dozen lines below its heading; a fixed
# short unit window (or matching the TOC row) misparses the multiplier by 1000x.
_INCOME_THOUSANDS = """\
### Table of Contents

| Item 1. | Consolidated Statements of Operations | 3 |
| Item 2. | Management's Discussion and Analysis | 26 |

### Consolidated Statements of Operations

(unaudited)

(in thousands, except per share data)

|  | Three Months Ended<br>June 30, 2026 | Three Months Ended<br>June 30, 2025 | Six Months Ended<br>June 30, 2026 | Six Months Ended<br>June 30, 2025 |
| --- | --- | --- | --- | --- |
| Revenues | $ 12,559,938 | $ 11,079,166 | $ 24,809,695 | $ 21,621,967 |
| Cost of revenues | 6,036,965 | 5,166,614 | 12,000,000 | 10,000,000 |
| Marketing | 700,000 | 650,000 | 1,400,000 | 1,300,000 |
| Technology and development | 800,000 | 750,000 | 1,600,000 | 1,500,000 |
| General and administrative | 630,363 | 600,000 | 1,200,000 | 1,150,000 |
| Operating income | 4,392,610 | 3,500,000 | 8,000,000 | 7,000,000 |
| Provision for income taxes | 400,000 | 350,000 | 800,000 | 700,000 |
| Net income | 3,992,610 | 3,150,000 | 7,200,000 | 6,300,000 |
"""


def test_income_units_thousands_via_heading_anchor(monkeypatch) -> None:
    _patch(monkeypatch, _INCOME_THOUSANDS)
    payload = income_filing.build_income_sankey_from_filing("TEST")
    nodes = {n["id"]: n["value"] for n in payload["nodes"]}
    # thousands, not millions: $12.56B, not $12.56T.
    assert nodes["revenue"] == 12_559_938 * 1_000
    assert nodes["costOfRevenue"] == 6_036_965 * 1_000


def test_income_opex_anchored_on_operating_income(monkeypatch) -> None:
    # Marketing + "Technology and development" aren't named by the classifier, so
    # R&D+SG&A alone understate opex. operatingExpense must be revenue − cost −
    # operating income so the Sankey balances and the uncaptured lines don't leak.
    _patch(monkeypatch, _INCOME_THOUSANDS)
    payload = income_filing.build_income_sankey_from_filing("TEST")
    nodes = {n["id"]: n["value"] for n in payload["nodes"]}
    assert nodes["operatingExpense"] == (12_559_938 - 6_036_965 - 4_392_610) * 1_000
    # grossProfit exactly splits into operating income + operating expense.
    assert nodes["grossProfit"] == pytest.approx(nodes["operatingIncome"] + nodes["operatingExpense"])


# No cost-of-revenue line (telecom/cable presentation) — the parser can't build a
# gross-profit split, so it must fail over to yfinance rather than emit garbage.
_INCOME_NO_COST = """\
### Consolidated Statements of Operations

(in millions)

|  | Three Months Ended June 30, 2026 | Three Months Ended June 30, 2025 |
| --- | --- | --- |
| Revenue | $ 29,940 | $ 30,313 |
| Programming and production | 8,389 | 7,576 |
| Marketing and promotion | 2,258 | 2,168 |
| Depreciation | 2,391 | 2,349 |
| Operating income | 5,160 | 5,992 |
| Net income | 3,419 | 3,000 |
"""


def test_income_no_cost_of_revenue_fails_over(monkeypatch) -> None:
    _patch(monkeypatch, _INCOME_NO_COST)
    assert income_filing.build_income_sankey_from_filing("TEST") is None


# Cash flow with a quarterly decoy column LAST (so a positional "last 2026 wins"
# would grab it), thousands units, and a Q3 nine-month period-to-date span.
_CASHFLOW_NINE_MONTH = """\
### Consolidated Statements of Cash Flows

(in thousands)

|  | Nine Months Ended<br>May 28, 2026 | Nine Months Ended<br>May 29, 2025 | Three Months Ended<br>May 28, 2026 |
| --- | --- | --- | --- |
| Net cash provided by operating activities | 45,702,000 | 11,795,000 | 15,000,000 |
| Expenditures for property, plant, and equipment | ( 19,602,000 ) | ( 10,199,000 ) | ( 6,000,000 ) |
"""


def test_cashflow_ytd_column_units_and_period(monkeypatch) -> None:
    _patch(monkeypatch, _CASHFLOW_NINE_MONTH, report_date="2026-05-28")
    cf = income_filing.build_cashflow_context("TEST")
    # YTD column, not the quarterly decoy (would be 15,000,000).
    assert cf["ocf"] == 45_702_000 * 1_000
    # "Expenditures for property…" is recognized as capex; reported positive.
    assert cf["capex"] == 19_602_000 * 1_000
    assert cf["fcf"] == (45_702_000 - 19_602_000) * 1_000
    assert cf["period"] == "nine-month"


# Unit stated ONLY inline in the heading title — the match must not consume it.
_INCOME_INLINE_UNIT = """\
## CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (In thousands, except per share data)

|  | Three Months Ended June 30, 2026 | Three Months Ended June 30, 2025 |
| --- | --- | --- |
| Net revenue | $ 5,000,000 | $ 4,000,000 |
| Cost of revenue | 2,000,000 | 1,600,000 |
| Research and development | 500,000 | 400,000 |
| Selling, general and administrative | 800,000 | 700,000 |
| Operating income | 1,700,000 | 1,300,000 |
| Provision for income taxes | 200,000 | 150,000 |
| Net income | 1,500,000 | 1,150,000 |
"""


def test_income_unit_inline_in_title(monkeypatch) -> None:
    _patch(monkeypatch, _INCOME_INLINE_UNIT)
    payload = income_filing.build_income_sankey_from_filing("TEST")
    nodes = {n["id"]: n["value"] for n in payload["nodes"]}
    assert nodes["revenue"] == 5_000_000 * 1_000  # thousands from the title, not millions


# "Cost of revenues, exclusive of depreciation…" understates COGS → must fail over.
_INCOME_EXCLUSIVE_COST = """\
### Consolidated Statements of Operations

(in millions)

|  | Three Months Ended June 30, 2026 | Three Months Ended June 30, 2025 |
| --- | --- | --- |
| Revenues | $ 10,000 | $ 9,000 |
| Cost of revenues, exclusive of depreciation and amortization shown separately below | 3,000 | 2,800 |
| Depreciation and amortization | 2,000 | 1,900 |
| Operating income | 5,000 | 4,300 |
| Net income | 4,000 | 3,400 |
"""


def test_income_exclusive_of_da_cost_fails_over(monkeypatch) -> None:
    _patch(monkeypatch, _INCOME_EXCLUSIVE_COST)
    assert income_filing.build_income_sankey_from_filing("TEST") is None


# operatingIncome slightly exceeds gross profit (rounding / near-zero opex): the
# injected operatingExpense would be negative — must NOT be injected.
_INCOME_OI_NEAR_GP = """\
### Consolidated Statements of Operations

(in millions)

|  | Three Months Ended June 30, 2026 | Three Months Ended June 30, 2025 |
| --- | --- | --- |
| Revenue | $ 1,000 | $ 900 |
| Cost of revenue | 400 | 380 |
| Operating income | 605 | 520 |
| Net income | 500 | 430 |
"""


def test_income_injection_skipped_when_negative(monkeypatch) -> None:
    # grossProfit = 600, operatingIncome = 605 (within the 1.02 gate). Injecting
    # operatingExpense = 600 − 605 = −5 would emit a negative Sankey link; the
    # guard must skip injection and leave no negative operating-expense node.
    _patch(monkeypatch, _INCOME_OI_NEAR_GP)
    payload = income_filing.build_income_sankey_from_filing("TEST")
    nodes = {n["id"]: n.get("value") for n in payload["nodes"]}
    assert nodes.get("operatingExpense") is None or nodes["operatingExpense"] >= 0
    for link in payload["links"]:
        assert link["value"] >= 0


# capex stem also appears in a "property HELD for sale" investing line placed
# before the real capex line — must skip it and take the real one.
_CASHFLOW_HELD_DECOY = """\
### Consolidated Statements of Cash Flows

(in millions)

|  | Six Months Ended June 30, 2026 | Six Months Ended June 30, 2025 |
| --- | --- | --- |
| Net cash provided by operating activities | 500 | 400 |
| Purchases of property held for sale | ( 999 ) | ( 888 ) |
| Purchases of property and equipment | ( 120 ) | ( 100 ) |
"""


def test_cashflow_capex_skips_held_line(monkeypatch) -> None:
    _patch(monkeypatch, _CASHFLOW_HELD_DECOY)
    cf = income_filing.build_cashflow_context("TEST")
    assert cf["capex"] == 120 * 1_000_000  # the real capex line, not "held for sale" (999)
