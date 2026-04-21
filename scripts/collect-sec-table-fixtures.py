"""Dump real SEC 10-K / 10-Q `<table>` HTML + current flat-markdown output as
golden-file fixtures for the rule-based `_table_to_md` parser.

Usage:
    export TERRAFIN_SEC_USER_AGENT="You <you@example.com>"
    python scripts/collect-sec-table-fixtures.py \
        --out tests/data/fixtures/sec_edgar_tables \
        --tickers AAPL,MSFT,GOOGL,JPM,BAC,PGR,GE,BA,WMT,COST,JNJ,XOM,PLD,NVDA,TSM \
        --forms 10-K,10-Q \
        --per-filing-cap 30 \
        --min-distinct-patterns 20

The script:
  1. Fetches each ticker × form via the existing `get_sec_data(..., parse=False)`
     so rate-limit + User-Agent wiring is reused.
  2. Parses with `sp.Edgar10QParser` exactly like `parser.py:_parse_filing`.
  3. For each TableElement, tags it by pattern fingerprint (colspan-header,
     dollar-split, paren-negative, footnote-marker, empty-spacer-columns,
     multi-row-header, mixed-text-numeric, nested-table, units-row,
     level-hierarchy, rowspan).
  4. Writes `<table>` HTML + current flat markdown + metadata to `out/tables/`
     and appends to `out/manifest.jsonl`.
  5. Curates: buckets by sorted pattern tuple, keeps up to 2 fixtures per
     bucket; fails if fewer than `--min-distinct-patterns` fingerprints
     survive.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class TableRecord:
    ticker: str
    form: str
    accession: str
    filing_idx: int
    table_idx: int
    nearest_section_title: str | None
    html: str
    flat_md: str
    patterns: tuple[str, ...]
    row_count: int
    col_count: int


def _tag_patterns(table_html: str) -> tuple[tuple[str, ...], int, int]:
    """Return (sorted-pattern-tags, row_count, col_count) for a <table> HTML string."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(table_html, "html.parser")
    table = soup.find("table")
    if table is None:
        return ((), 0, 0)

    tags: set[str] = set()

    trs = table.find_all("tr")
    row_count = len(trs)
    col_count = 0

    # Collect row-level data to reason about columns
    rows: list[list[dict[str, Any]]] = []
    for tr in trs:
        row = []
        for cell in tr.find_all(["th", "td"]):
            colspan = int(cell.get("colspan") or 1)
            rowspan = int(cell.get("rowspan") or 1)
            text = cell.get_text(" ", strip=True)
            # Normalize tokens for pattern recognition
            text_n = text.replace("\xa0", " ").replace("\u200b", "").strip()
            row.append({"text": text_n, "colspan": colspan, "rowspan": rowspan, "tag": cell.name})
            if colspan > 1:
                tags.add("colspan-header" if cell.name == "th" else "colspan-cell")
            if rowspan > 1:
                tags.add("rowspan")
            if cell.find("table") is not None:
                tags.add("nested-table")
            if cell.find("sup") is not None:
                tags.add("footnote-marker")
        rows.append(row)
        col_count = max(col_count, sum(c["colspan"] for c in row))

    # dollar-split / paren-negative / footnote-marker / units-row
    for row in rows:
        for cell in row:
            t = cell["text"]
            if t in {"$", "(", ")", "%"}:
                tags.add("dollar-split")
            if re.fullmatch(r"\(\$?\d[\d,\.]*\)", t):
                tags.add("paren-negative")
            if re.search(r"\(\d+\)\s*$", t):
                tags.add("footnote-marker")
            if re.fullmatch(r"\(in (millions|thousands|billions)[^)]*\)", t, re.I):
                tags.add("units-row")

    # empty-spacer-columns: expand cells honoring colspan into a dense grid,
    # then check per column whether every body row is blank.
    grid = _dense_grid(rows)
    if grid:
        body = grid[1:] or grid
        for c in range(len(grid[0])):
            if all((not row[c].strip()) for row in body):
                tags.add("empty-spacer-columns")
                break

    # multi-row-header: first 2+ rows all (mostly) <th>
    header_run = 0
    for row in rows:
        if not row:
            continue
        if sum(1 for c in row if c["tag"] == "th") >= max(1, len(row) // 2):
            header_run += 1
        else:
            break
    if header_run >= 2:
        tags.add("multi-row-header")

    # mixed-text-numeric: first column has long text, others mostly numeric
    if rows and len(rows) >= 2:
        first_col_texts = [r[0]["text"] for r in rows if r]
        if any(len(t) > 25 for t in first_col_texts):
            other_texts = [c["text"] for r in rows for c in r[1:] if c["text"]]
            if other_texts:
                numeric = sum(1 for t in other_texts if re.fullmatch(r"[\$\(\)\-%,\.\d\s]+", t))
                if numeric / len(other_texts) >= 0.6:
                    tags.add("mixed-text-numeric")

    # level-hierarchy: Level 1 / Level 2 / Level 3
    text_join = " ".join(c["text"] for r in rows for c in r)
    if re.search(r"\bLevel\s*1\b", text_join) and re.search(r"\bLevel\s*[23]\b", text_join):
        tags.add("level-hierarchy")

    return (tuple(sorted(tags)), row_count, col_count)


def _dense_grid(rows: list[list[dict[str, Any]]]) -> list[list[str]]:
    """Expand colspan into a dense 2-D list of cell text. Ignores rowspan for tagging."""
    if not rows:
        return []
    max_cols = 0
    for row in rows:
        max_cols = max(max_cols, sum(c["colspan"] for c in row))
    out: list[list[str]] = []
    for row in rows:
        flat: list[str] = []
        for cell in row:
            flat.extend([cell["text"]] * cell["colspan"])
        while len(flat) < max_cols:
            flat.append("")
        out.append(flat[:max_cols])
    return out


def _collect_from_html(html: str) -> list[tuple[Any, str | None]]:
    """Run sec_parser on the filing HTML, return list of (TableElement, nearest_title)."""
    import sec_parser as sp
    from sec_parser.semantic_elements import TableElement, TitleElement, TopSectionTitle

    elements = sp.Edgar10QParser().parse(html)
    out: list[tuple[Any, str | None]] = []
    last_title: str | None = None
    for el in elements:
        if isinstance(el, (TopSectionTitle, TitleElement)):
            last_title = (el.text or "").strip()[:200]
        elif isinstance(el, TableElement):
            out.append((el, last_title))
    return out


def _safe_accession(accession: str) -> str:
    return re.sub(r"[^0-9a-zA-Z-]+", "-", accession)


def _dump_records(records: list[TableRecord], out_dir: Path, keep_per_fp: int, min_patterns: int):
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Curate: bucket by fingerprint, keep up to N per bucket
    buckets: dict[tuple[str, ...], list[TableRecord]] = {}
    for rec in records:
        buckets.setdefault(rec.patterns, []).append(rec)

    curated: list[TableRecord] = []
    for fp, recs in buckets.items():
        # Prefer variety across tickers inside a bucket
        seen_tickers: set[str] = set()
        kept = []
        for r in recs:
            if len(kept) >= keep_per_fp:
                break
            if r.ticker in seen_tickers and len(recs) > keep_per_fp:
                continue
            kept.append(r)
            seen_tickers.add(r.ticker)
        curated.extend(kept)

    if len(buckets) < min_patterns:
        raise SystemExit(
            f"Only {len(buckets)} distinct pattern fingerprints found; need ≥{min_patterns}. "
            "Add more tickers or a different form mix."
        )

    manifest_path = out_dir / "manifest.jsonl"
    manifest_lines: list[str] = []
    for rec in curated:
        base = f"{rec.ticker}_{rec.form.replace('-', '')}_{_safe_accession(rec.accession)}_{rec.table_idx:03d}"
        html_path = tables_dir / f"{base}.html"
        md_path = tables_dir / f"{base}.md"
        html_path.write_text(rec.html, encoding="utf-8")
        md_path.write_text(rec.flat_md, encoding="utf-8")
        manifest_lines.append(
            json.dumps(
                {
                    "ticker": rec.ticker,
                    "form": rec.form,
                    "accession": rec.accession,
                    "filing_idx": rec.filing_idx,
                    "table_idx": rec.table_idx,
                    "nearest_section_title": rec.nearest_section_title,
                    "html_path": f"tables/{html_path.name}",
                    "md_path": f"tables/{md_path.name}",
                    "patterns": list(rec.patterns),
                    "row_count": rec.row_count,
                    "col_count": rec.col_count,
                    "flat_md_lines": rec.flat_md.count("\n") + (1 if rec.flat_md else 0),
                    "original_html_bytes": len(rec.html),
                },
                ensure_ascii=False,
            )
        )
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    readme = out_dir / "README.md"
    pattern_counts: dict[str, int] = {}
    for rec in curated:
        for p in rec.patterns:
            pattern_counts[p] = pattern_counts.get(p, 0) + 1
    readme_lines = [
        "# SEC 10-K / 10-Q table fixtures",
        "",
        "Regenerate:",
        "",
        "```bash",
        "export TERRAFIN_SEC_USER_AGENT='You <you@example.com>'",
        "python scripts/collect-sec-table-fixtures.py --out tests/data/fixtures/sec_edgar_tables",
        "```",
        "",
        f"**{len(curated)}** fixtures covering **{len(buckets)}** distinct pattern fingerprints.",
        "",
        "Each fixture stores:",
        "",
        "- `<base>.html` — raw `<table>` HTML extracted via `element.get_source_code()`",
        "- `<base>.md` — current flattened markdown (`element.table_to_markdown()`) — the broken output",
        "",
        "## Pattern coverage",
        "",
        "| Tag | # fixtures |",
        "|-----|-----------|",
    ]
    for p in sorted(pattern_counts):
        readme_lines.append(f"| `{p}` | {pattern_counts[p]} |")
    readme.write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    try:
        rel = tables_dir.resolve().relative_to(REPO_ROOT)
    except ValueError:
        rel = tables_dir
    print(f"wrote {len(curated)} fixtures to {rel}")
    print(f"distinct pattern fingerprints: {len(buckets)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--tickers",
        default="AAPL,MSFT,GOOGL,JPM,BAC,PGR,GE,BA,WMT,COST,JNJ,XOM,PLD,NVDA,TSM",
    )
    parser.add_argument("--forms", default="10-K,10-Q")
    parser.add_argument("--per-filing-cap", type=int, default=30)
    parser.add_argument("--keep-per-fingerprint", type=int, default=2)
    parser.add_argument("--min-distinct-patterns", type=int, default=20)
    args = parser.parse_args()

    from TerraFin.data.providers.corporate.filings.sec_edgar import (
        get_company_filings,
        get_sec_data,
        get_ticker_to_cik_dict_cached,
    )

    cik_map = get_ticker_to_cik_dict_cached()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]

    records: list[TableRecord] = []
    for ticker in tickers:
        cik = cik_map.get(ticker)
        if cik is None:
            print(f"[skip] no CIK for {ticker}", file=sys.stderr)
            continue
        for form in forms:
            try:
                filings_df = get_company_filings(cik, include_8k=False)
                filings_df = filings_df[filings_df.form == form]
                if len(filings_df) == 0:
                    print(f"[skip] {ticker} {form}: no filings", file=sys.stderr)
                    continue
                accession = filings_df.accessionNumber.iloc[0]
                html = get_sec_data(ticker, filing_type=form, filing_index=0, parse=False)
            except Exception as exc:
                print(f"[warn] {ticker} {form}: {exc}", file=sys.stderr)
                continue
            try:
                tables = _collect_from_html(html)
            except Exception as exc:
                print(f"[warn] {ticker} {form} parse: {exc}", file=sys.stderr)
                continue
            if not tables:
                continue
            print(f"[ok] {ticker} {form}: {len(tables)} tables")
            count = 0
            for idx, (el, section) in enumerate(tables):
                if count >= args.per_filing_cap:
                    break
                try:
                    table_html = el.get_source_code() or ""
                    flat_md = el.table_to_markdown() or ""
                except Exception as exc:
                    print(f"[warn] table {idx} extract: {exc}", file=sys.stderr)
                    continue
                if not table_html.strip():
                    continue
                patterns, rows, cols = _tag_patterns(table_html)
                # Skip trivial single-row "tables" (often layout divs misclassified)
                if rows < 2 or cols < 2:
                    continue
                records.append(
                    TableRecord(
                        ticker=ticker,
                        form=form,
                        accession=accession,
                        filing_idx=0,
                        table_idx=idx,
                        nearest_section_title=section,
                        html=table_html,
                        flat_md=flat_md,
                        patterns=patterns,
                        row_count=rows,
                        col_count=cols,
                    )
                )
                count += 1

    print(f"collected {len(records)} raw records")
    _dump_records(records, args.out, args.keep_per_fingerprint, args.min_distinct_patterns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
