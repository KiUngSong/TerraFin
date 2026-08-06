"""Income-statement Sankey built from a company's latest 10-Q/10-K FILING.

yfinance's structured quarterly financials lag the actual SEC filing by days to
weeks, so the income Sankey is stale the quarter right after earnings. This
module deterministically parses the primary income statement out of the filing
document TerraFin already fetches (no yfinance, no LLM — pure table parse) and
assembles it through the SAME `_assemble_income_sankey` the yfinance path uses,
so it is a drop-in fallback when yfinance is a quarter behind.
"""
import logging
import re

from .payloads import (
    _assemble_income_sankey,
    build_filing_document_payload,
    build_filings_list_payload,
)

log = logging.getLogger(__name__)

_M = 1_000_000  # default: 10-Q line items are reported in millions

_UNIT_RE = re.compile(r"\(in\s+(thousands|millions|billions)", re.I)
_UNIT_MULT = {"thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}


def _quarter_col(cell: str) -> bool:
    """True for a QUARTER period-column header (not a YTD six/nine-month column).
    Handles the common dialects: 'Three Months Ended ...' and 'Quarter Ended ...'."""
    cl = cell.lower()
    if any(x in cl for x in ("six month", "nine month", "year ended", "twelve month", "fiscal year")):
        return False
    return ("three month" in cl) or ("quarter ended" in cl) or ("quarter end" in cl)


def _cells(line: str) -> list[str]:
    parts = [c.strip() for c in line.split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _num(cell: str):
    s = (cell or "").strip()
    if not s or s in ("—", "-", "–"):
        return None
    neg = "(" in s and ")" in s
    s = s.replace("$", "").replace(",", "").replace("(", "").replace(")", "").replace("%", "").strip()
    m = re.match(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    v = float(m.group(0))
    return -v if neg else v


def _classify(label: str) -> str | None:
    l = re.sub(r"<br\s*/?>", " ", label).lower().strip()
    if "cost of revenue" in l or "cost of sales" in l or "cost of goods" in l:
        # "…exclusive of depreciation and amortization shown separately below"
        # understates COGS (D&A sits in its own line) → gross profit/margin would
        # be overstated. Don't treat it as a clean cost line; the missing
        # costOfRevenue then trips the sanity gate → fail over to yfinance.
        if "exclusiv" in l:
            return None
        return "costOfRevenue"
    if l in ("revenues", "revenue", "total revenues", "total revenue", "net revenues", "net revenue", "net sales", "total net sales"):
        return "revenue"
    # "gross profit" only. A "Gross margin 54 %" row is a RATIO, and _num strips the
    # percent sign, so accepting it here made $54M the gross profit and the override
    # below then set costOfRevenue = revenue - 54.
    if l.startswith("gross profit"):
        return "grossProfit"
    if "research and development" in l:
        return "researchAndDevelopment"
    if "selling, general and administrative" in l or "selling, general, and administrative" in l:
        return "sga_direct"
    if "sales and marketing" in l or "selling and marketing" in l:
        return "sm"
    if l.startswith("general and administrative") or "general and administrative" in l:
        return "ga"
    if "income from operations" in l or l in ("operating income", "operating income (loss)", "income (loss) from operations"):
        return "operatingIncome"
    # "…from continuing operations before income taxes and equity income" (AMD) puts
    # words between "income" and "before", so match on the tax side of the phrase.
    if "before income tax" in l or ("income before" in l and "tax" in l) or "pretax income" in l:
        return "pretaxIncome"
    if ("provision for income tax" in l) or ("income tax provision" in l) or ("income tax expense" in l) or ("provision" in l and "income tax" in l):
        return "taxProvision"
    if l.startswith("net income") and not any(x in l for x in ("per ", "available", "attributable", "per common", "per share")):
        return "netIncome"
    return None


# The statement TITLE as a markdown heading — preferred over the bare text, which
# also hits the table-of-contents row and narrative mentions. A TOC match's 40-line
# header scan reaches the real table far below, but its unit note is then out of
# window, so the real rows get parsed with the wrong multiplier (a 1000x error for a
# thousands-reporting filer like NFLX). Headings land ON the real statement; the
# bare-text pattern is the fallback for filings whose parser output has no heading.
_STMT_HEADING_RE = re.compile(
    r"(?m)^#{1,6}\s+.*STATEMENTS?\s+OF\s+(?:OPERATIONS|INCOME|EARNINGS).*$", re.I)
_STMT_TEXT_RE = re.compile(
    r"(?:STATEMENTS?\s+OF\s+(?:INCOME|OPERATIONS|EARNINGS)|INCOME\s+STATEMENTS?)", re.I)


def _line_start(md: str, pos: int) -> int:
    """Offset of the start of the line containing `pos`."""
    return md.rfind("\n", 0, pos) + 1


def _statement_starts(md: str) -> list[int]:
    """Offsets at the START of each candidate statement-title line — headings
    first (they land on the real statement), then bare-text mentions. Slicing from
    the line start (not the match end) keeps a unit note stated INLINE in the title
    (e.g. "…STATEMENTS OF OPERATIONS (In thousands)") inside the later unit scan."""
    return [_line_start(md, m.start()) for m in _STMT_HEADING_RE.finditer(md)] + \
           [_line_start(md, m.start()) for m in _STMT_TEXT_RE.finditer(md)]


def _parse_income_statement(md: str, report_date: str):
    """Parse the primary income statement's current + prior-year QUARTER columns
    from a 10-Q markdown. Returns (cur, prior, as_of, prior_as_of) as canonical
    scalar maps in DOLLARS, or (None, None, None, None) when it can't be located."""
    ry = report_date[:4]
    py = str(int(ry) - 1)
    for start in _statement_starts(md):
        lines = md[start:].splitlines()
        cur_col = prior_col = rows_start = None
        for i, ln in enumerate(lines[:40]):
            if "|" not in ln:
                continue
            cells = _cells(ln)
            if any(_quarter_col(c) for c in cells) and ry in ln:
                for idx, c in enumerate(cells):
                    if not _quarter_col(c):
                        continue
                    ym = re.search(r"(20\d{2})", c)
                    if ym and ym.group(1) == ry:
                        cur_col = idx
                    elif ym and ym.group(1) == py:
                        prior_col = idx
                if cur_col is not None:
                    rows_start = i + 1
                    break
        if cur_col is None:
            continue
        # Unit multiplier: the nearest "(in thousands|millions|billions)" AT OR
        # ABOVE the located header row. A fixed short window fails when the title
        # is a heading with preamble before the note (NFLX: heading, "(unaudited)",
        # then "(in thousands…)" a dozen lines above the table); scanning to the
        # header and keeping the last hit picks the table's own unit. Defaults to
        # millions (the 10-Q norm) when the statement leaves it unstated.
        mult = _M
        for _ln in lines[:rows_start]:
            _um = _UNIT_RE.search(_ln)
            if _um:
                mult = _UNIT_MULT[_um.group(1).lower()]
        cur: dict = {}
        prior: dict = {}
        sm = ga = p_sm = p_ga = None
        for ln in lines[rows_start:]:
            s = ln.strip()
            if s.startswith("#") or s.lower().startswith("see accompanying") or "integral part" in s.lower():
                break
            if "|" not in ln:
                continue
            cells = _cells(ln)
            if len(cells) <= cur_col:
                continue
            key = _classify(cells[0])
            if not key:
                continue
            cv = _num(cells[cur_col])
            pv = _num(cells[prior_col]) if (prior_col is not None and len(cells) > prior_col) else None
            if key == "sm":
                sm, p_sm = cv, pv
            elif key == "ga":
                ga, p_ga = cv, pv
            elif key == "sga_direct":
                cur.setdefault("sellingGeneralAdmin", cv)
                prior.setdefault("sellingGeneralAdmin", pv)
            else:
                if cv is not None:
                    cur.setdefault(key, cv)
                if pv is not None:
                    prior.setdefault(key, pv)
        if "sellingGeneralAdmin" not in cur and (sm is not None or ga is not None):
            cur["sellingGeneralAdmin"] = (sm or 0) + (ga or 0)
            prior["sellingGeneralAdmin"] = (p_sm or 0) + (p_ga or 0)
        rev, cost = cur.get("revenue"), cur.get("costOfRevenue")
        # Sanity gate: a real income statement, not a mis-parsed table. The column
        # is read positionally (no tie-out), so cross-check internal consistency —
        # a period/column shift breaks these invariants. A bad parse fails over to
        # the yfinance base rather than emitting garbage.
        if not (rev and cost and 0 < cost < rev):
            continue
        _oi = cur.get("operatingIncome")
        if _oi is not None and _oi > (rev - cost) * 1.02:   # op income can't exceed gross profit
            continue
        if any(cur.get(k) is not None and cur.get(k) < 0          # opex lines are positive spends
               for k in ("researchAndDevelopment", "sellingGeneralAdmin")):  # (not tax — can be a benefit)
            continue
        # A reported Gross profit is authoritative; revenue − costOfRevenue is not.
        # Filers put lines between the two (AMD: "Amortization of acquisition-related
        # intangibles"), so the subtraction overstates gross profit and every margin
        # derived from it. Absorb the gap into cost so the reported subtotal wins and
        # the opex anchor below still balances.
        for _d in (cur, prior):
            _rv, _gp = _d.get("revenue"), _d.get("grossProfit")
            # >=2% of revenue: a stray ratio row (54 against revenue 11,536) is not a
            # credible gross profit, and trusting it would wipe out costOfRevenue.
            if _rv and _gp is not None and 0.02 * _rv <= _gp < _rv:
                _d["costOfRevenue"] = _rv - _gp
            elif _gp is not None and _rv and _gp < 0.02 * _rv:
                log.warning("income_filing: implausible grossProfit %s vs revenue %s — ignoring", _gp, _rv)
                _d.pop("grossProfit", None)
        cur = {k: (v * mult if v is not None else None) for k, v in cur.items()}
        prior = {k: (v * mult if v is not None else None) for k, v in prior.items()}
        # Anchor total operating expense on the REPORTED operating income
        # (revenue − costOfRevenue − operatingIncome). The assembler otherwise
        # derives opex from R&D + SG&A alone, which understates it for filers whose
        # opex is split into non-standard line items the classifier doesn't capture
        # (streaming: marketing / technology & development; telecom: programming);
        # the uncaptured lines would leak and the Sankey wouldn't balance. The
        # residual surfaces as "Other opex" instead. Reported subtotals (revenue,
        # operatingIncome) are unambiguous single lines, so this stays exact.
        for _d in (cur, prior):
            _rv, _cst, _oi = _d.get("revenue"), _d.get("costOfRevenue"), _d.get("operatingIncome")
            if _rv is not None and _cst is not None and _oi is not None:
                _opex = (_rv - _cst) - _oi
                _captured = (_d.get("researchAndDevelopment") or 0) + (_d.get("sellingGeneralAdmin") or 0)
                # Only inject when it's a valid total: non-negative (the assembler's
                # links must be ≥ 0) AND at least the opex lines already captured
                # (else the residual "Other opex" goes negative and the Sankey won't
                # balance). Otherwise leave it for the assembler's R&D+SG&A default.
                if _opex >= _captured:
                    _d["operatingExpense"] = _opex
        prior_as_of = f"{py}{report_date[4:]}"
        return cur, prior, report_date, prior_as_of
    return None, None, None, None


def build_income_sankey_from_filing(ticker: str, form: str = "10-Q") -> dict | None:
    """Income Sankey for `ticker`'s latest `form`, sourced from the FILING itself.
    Returns the same shape as build_income_sankey_payload, or None when the filing
    or its income statement can't be parsed (caller then keeps the yfinance base)."""
    normalized = ticker.upper()
    lst = build_filings_list_payload(normalized)
    meta = (lst.get("latestByForm") or {}).get(form)
    if not meta or not meta.get("accession") or not meta.get("reportDate"):
        return None
    try:
        doc = build_filing_document_payload(
            normalized, meta["accession"], meta.get("primaryDocument"), form=form)
    except Exception as e:  # pragma: no cover - network/parse
        log.warning("income_from_filing %s: document fetch failed (%s)", ticker, e)
        return None
    md = (doc or {}).get("markdown") or ""
    cur, prior, as_of, prior_as_of = _parse_income_statement(md, meta["reportDate"])
    if not cur:
        return None
    return _assemble_income_sankey(
        cur, prior or {}, ticker=normalized, period="quarter",
        current_date=as_of, prior_date=prior_as_of)


_CF_LABELS = {
    # capex is worded several standard ways: "purchases of…", "expenditures for…"
    # (Micron, Intel), "additions to…", "payments to acquire…". Match on the stem
    # so the Oxford-comma / "plant and equipment" variants all resolve.
    "capex": ("purchases of property", "expenditures for property", "additions to property",
              "payments to acquire property", "capital expenditures"),
    "ocf": ("net cash provided by operating activities", "net cash from operating activities",
            "net cash generated by operating activities", "cash flows from operating activities"),
}


def build_cashflow_context(ticker: str, form: str = "10-Q") -> dict | None:
    """Capex + operating cash flow (→ free cash flow) for `ticker`'s latest filing,
    parsed deterministically from the cash-flow statement (10-Q figures are the
    period-to-date/six-month cumulative). Returns dollars, current + prior-year, or
    None when it can't be located. FCF = operating cash flow − capex."""
    normalized = ticker.upper()
    lst = build_filings_list_payload(normalized)
    meta = (lst.get("latestByForm") or {}).get(form)
    if not meta or not meta.get("accession") or not meta.get("reportDate"):
        return None
    try:
        md = (build_filing_document_payload(
            normalized, meta["accession"], meta.get("primaryDocument"), form=form) or {}).get("markdown") or ""
    except Exception as e:  # pragma: no cover
        log.warning("cashflow_context %s: document fetch failed (%s)", ticker, e)
        return None
    ry = meta["reportDate"][:4]
    py = str(int(ry) - 1)
    # Heading-anchored (then bare-text fallback), same as the income statement —
    # a bare "statements of cash flows" also matches the table-of-contents row.
    starts = [_line_start(md, mm.start()) for mm in re.finditer(
                  r"(?m)^#{1,6}\s+.*STATEMENTS?\s+OF\s+CASH\s+FLOWS?.*$", md, re.I)]
    starts += [_line_start(md, mm.start()) for mm in re.finditer(
                   r"STATEMENTS?\s+OF\s+CASH\s+FLOWS?", md, re.I)]
    mult = _M
    lines = None
    period_label = None
    cur_col = prior_col = rows_start = None
    for start in starts:
        _lines = md[start:].splitlines()
        cur_col = prior_col = rows_start = None
        for i, ln in enumerate(_lines[:20]):
            if "|" not in ln:
                continue
            cells = _cells(ln)
            if ry in ln and py in ln and sum(1 for c in cells if re.search(r"20\d{2}", c)) >= 2:
                for idx, c in enumerate(cells):
                    if _quarter_col(c):
                        continue  # 10-Q cash flows are period-to-date (YTD); never a quarterly column
                    ym = re.search(r"(20\d{2})", c)
                    if ym and ym.group(1) == ry:
                        cur_col = idx
                    elif ym and ym.group(1) == py:
                        prior_col = idx
                if cur_col is not None:
                    rows_start = i + 1
                    # Period-to-date span (Q1→three, Q2→six, Q3→nine month). It can
                    # sit in the column cell (NFLX), the label cell (MU), or a row
                    # above the dates row — scan the whole header region. A filer
                    # showing both quarterly and YTD columns states both spans, but
                    # the selected column is always the YTD one, so prefer the widest.
                    _region = " ".join(_lines[:rows_start]).lower()
                    period_label = ("nine-month" if "nine month" in _region else
                                    "six-month" if "six month" in _region else
                                    "three-month" if "three month" in _region else "six-month")
                    break
        if cur_col is None:
            continue
        lines = _lines
        for _ln in _lines[:rows_start]:   # nearest unit note at/above the header row
            _um = _UNIT_RE.search(_ln)
            if _um:
                mult = _UNIT_MULT[_um.group(1).lower()]
        break
    if cur_col is None:
        return None
    got: dict = {}
    for ln in lines[rows_start:rows_start + 160]:
        if "|" not in ln:
            continue
        cells = _cells(ln)
        if len(cells) <= cur_col:
            continue
        lab = re.sub(r"<[^>]+>", " ", cells[0]).lower().strip()
        # A capex stem ("…property") also appears in non-capex lines: property
        # HELD for sale / held under operating leases, and the supplemental non-cash
        # "capital expenditures ACCRUED" disclosure. Exclude those explicitly.
        if "held" in lab or "accrued" in lab:
            continue
        for key, pats in _CF_LABELS.items():
            if key in got:
                continue
            if any(p in lab for p in pats):
                cv = _num(cells[cur_col])
                if cv is None:
                    continue  # caption/section-header row (no value) — keep scanning for the real subtotal
                pv = _num(cells[prior_col]) if (prior_col is not None and len(cells) > prior_col) else None
                got[key] = (cv, pv)
        if "capex" in got and "ocf" in got:
            break
    if "capex" not in got or "ocf" not in got:
        return None
    (capex_c, capex_p), (ocf_c, ocf_p) = got["capex"], got["ocf"]
    # capex is an outflow reported as a positive spend; a zero/blank means the
    # row matched a caption, not the real figure — fail over rather than divide by it.
    if not capex_c or ocf_c is None:
        return None

    def _fcf(ocf, capex):
        return None if (ocf is None or capex is None) else (ocf - abs(capex))

    return {
        "capex": abs(capex_c) * mult,
        "ocf": ocf_c * mult,
        "fcf": None if _fcf(ocf_c, capex_c) is None else _fcf(ocf_c, capex_c) * mult,
        "prior_capex": None if capex_p is None else abs(capex_p) * mult,
        "prior_fcf": None if _fcf(ocf_p, capex_p) is None else _fcf(ocf_p, capex_p) * mult,
        "period": period_label or ("six-month" if form == "10-Q" else "annual"),
    }
