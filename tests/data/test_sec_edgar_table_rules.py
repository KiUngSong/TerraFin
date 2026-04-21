"""Golden-file tests for the rule-based SEC `<table>` → markdown rebuild.

Each fixture under ``tests/data/fixtures/sec_edgar_tables/tables/`` has:

- ``<base>.html`` — raw ``<table>`` HTML from the real filing
- ``<base>.md`` — the flattened ``sec_parser`` output (the broken state)
- ``<base>.expected.md`` — what ``_rebuild_table_markdown`` should produce,
  committed alongside the input. Regenerate with ``REGEN=1 pytest``.

When a parser rule changes, re-run with ``REGEN=1`` and review the diffs
before committing. The test is dumb (byte-compare against the expected
file) so every change lands as a reviewable snapshot update.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from TerraFin.data.providers.corporate.filings.sec_edgar.parser import (
    _rebuild_table_markdown,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sec_edgar_tables"
MANIFEST = FIXTURES_DIR / "manifest.jsonl"
TABLES_DIR = FIXTURES_DIR / "tables"


def _manifest_entries() -> list[dict]:
    if not MANIFEST.exists():
        return []
    entries = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


@pytest.mark.parametrize(
    "entry",
    _manifest_entries(),
    ids=lambda e: Path(e["html_path"]).stem,
)
def test_table_rebuild_matches_snapshot(entry: dict) -> None:
    html_path = FIXTURES_DIR / entry["html_path"]
    expected_path = html_path.with_suffix(".expected.md")

    html = html_path.read_text(encoding="utf-8")
    produced = _rebuild_table_markdown(html) or ""

    if os.environ.get("REGEN") == "1":
        expected_path.write_text(produced + ("\n" if produced and not produced.endswith("\n") else ""), encoding="utf-8")
        return

    if not expected_path.exists():
        pytest.fail(
            f"missing snapshot: {expected_path.relative_to(FIXTURES_DIR)}. "
            "Run `REGEN=1 pytest tests/data/test_sec_edgar_table_rules.py` to create it."
        )

    expected = expected_path.read_text(encoding="utf-8").rstrip("\n")
    actual = produced.rstrip("\n")
    assert actual == expected, (
        f"Rebuild diverged from snapshot for {entry['html_path']}. "
        "Re-run with REGEN=1 if the rule change is intentional."
    )
