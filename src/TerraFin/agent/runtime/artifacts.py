"""Artifact / capability-call dataclasses and shared focus-extractor helpers.

Pure data + small helpers used by both capability registration (focus
extractors / artifact builders) and session bookkeeping. No dependency on
session, capability, or context classes — those import from here.
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


ArtifactKind = Literal[
    "chart",
    "table",
    "report",
    "calendar_slice",
    "valuation_result",
    "portfolio_snapshot",
    "data_payload",
]


@dataclass(frozen=True, slots=True)
class TerraFinArtifact:
    artifact_id: str
    kind: ArtifactKind
    title: str
    session_id: str
    capability_name: str
    created_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


CapabilityHandler = Callable[..., dict[str, Any]]
FocusExtractor = Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[str, ...]]
ArtifactBuilder = Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], TerraFinArtifact | None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in items:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


@dataclass(frozen=True, slots=True)
class TerraFinCapabilityCall:
    capability_name: str
    called_at: datetime
    inputs: dict[str, Any]
    output_keys: tuple[str, ...]
    focus_items: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
