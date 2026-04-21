# SEC 10-K / 10-Q table fixtures

Regenerate:

```bash
export TERRAFIN_SEC_USER_AGENT='You <you@example.com>'
python scripts/collect-sec-table-fixtures.py --out tests/data/fixtures/sec_edgar_tables
```

**113** fixtures covering **74** distinct pattern fingerprints.

Each fixture stores:

- `<base>.html` — raw `<table>` HTML extracted via `element.get_source_code()`
- `<base>.md` — current flattened markdown (`element.table_to_markdown()`) — the broken output
- `<base>.expected.md` — the rule-based rebuild snapshot
  (`_rebuild_table_markdown` in `src/TerraFin/data/providers/corporate/filings/sec_edgar/parser.py`).
  Regenerate with `REGEN=1 pytest tests/data/test_sec_edgar_table_rules.py`
  and review the diff before committing.

## Rebuild quality

Of the 113 fixtures, **110 render as clean GFM tables** (header + separator +
aligned body rows, ≤50% empty cells in the body). The remaining **3 have
misaligned SEC HTML where the header and body rows use inconsistent
colspan segmentations for the same visible column** — a quirk of JPM /
BA / WMT's template engine, not something the rule set can recover without
semantic knowledge of the filing. These are documented for reference:

- `tables/JPM_10Q_0001628280-25-048859_007.html` — noninterest expense,
  Three/Nine-month columns with mismatched header spans.
- `tables/BA_10Q_0001628280-25-047023_029.html` — fair-value table where
  sub-header colspan doesn't match body cell widths.
- `tables/WMT_10K_0000104169-26-000055_001.html` — unit count table where
  `Square Feet` sub-labels (Minimum / Maximum / Average) land in different
  columns than their body values.

These remain wired to the `element.table_to_markdown()` fallback at the
call-site level via the `try/except` in `_table_to_md`.

## Pattern coverage

| Tag | # fixtures |
|-----|-----------|
| `colspan-cell` | 110 |
| `dollar-split` | 74 |
| `empty-spacer-columns` | 58 |
| `footnote-marker` | 53 |
| `level-hierarchy` | 16 |
| `mixed-text-numeric` | 73 |
| `paren-negative` | 33 |
| `rowspan` | 32 |
| `units-row` | 34 |
