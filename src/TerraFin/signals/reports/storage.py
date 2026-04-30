"""Persistent storage for rendered weekly reports.

Reports live as plain markdown under ~/.terrafin/reports/weekly/<as_of>.md
plus a sidecar JSON with metadata. Disk cost is negligible (KB-scale per
report) so we keep them indefinitely — multi-week stacking is the actual
product.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

REPORT_DIR = Path.home() / ".terrafin" / "reports" / "weekly"


@dataclass
class StoredReport:
    as_of: str
    generated_at: str
    is_sample: bool
    universe: list[str]
    markdown: str

    def summary(self) -> dict:
        return {
            "asOf": self.as_of,
            "generatedAt": self.generated_at,
            "isSample": self.is_sample,
            "universe": self.universe,
            "tickers": len(self.universe),
        }


def _meta_path(as_of: str) -> Path:
    return REPORT_DIR / f"{as_of}.json"


def _md_path(as_of: str) -> Path:
    return REPORT_DIR / f"{as_of}.md"


def save_report(as_of: date, markdown: str, is_sample: bool, universe: list[str]) -> StoredReport:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    record = StoredReport(
        as_of=as_of.isoformat(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        is_sample=is_sample,
        universe=universe,
        markdown=markdown,
    )
    _md_path(record.as_of).write_text(markdown, encoding="utf-8")
    _meta_path(record.as_of).write_text(
        json.dumps({k: v for k, v in asdict(record).items() if k != "markdown"}, indent=2),
        encoding="utf-8",
    )
    return record


def load_report(as_of: str) -> StoredReport | None:
    md_path = _md_path(as_of)
    meta_path = _meta_path(as_of)
    if not md_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        markdown = md_path.read_text(encoding="utf-8")
    except Exception:
        return None
    return StoredReport(
        as_of=meta.get("asOf") or meta.get("as_of") or as_of,
        generated_at=meta.get("generatedAt") or meta.get("generated_at", ""),
        is_sample=bool(meta.get("isSample", meta.get("is_sample", False))),
        universe=list(meta.get("universe") or []),
        markdown=markdown,
    )


def list_reports(limit: int | None = None) -> list[StoredReport]:
    if not REPORT_DIR.exists():
        return []
    entries = []
    for md in sorted(REPORT_DIR.glob("*.md"), reverse=True):
        rec = load_report(md.stem)
        if rec:
            entries.append(rec)
        if limit is not None and len(entries) >= limit:
            break
    return entries
