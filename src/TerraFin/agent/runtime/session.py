"""Session record + snapshot dataclass for the in-process agent runtime."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .artifacts import TerraFinArtifact, TerraFinCapabilityCall, _dedupe, _utc_now


@dataclass(frozen=True, slots=True)
class TerraFinAgentSessionSnapshot:
    session_id: str
    focus_items: tuple[str, ...]
    artifacts: tuple[TerraFinArtifact, ...]
    capability_calls: tuple[TerraFinCapabilityCall, ...]
    metadata: dict[str, Any]


@dataclass
class TerraFinAgentSession:
    session_id: str = field(default_factory=lambda: f"terrafin-session:{uuid4().hex}")
    focus_items: list[str] = field(default_factory=list)
    artifacts: list[TerraFinArtifact] = field(default_factory=list)
    capability_calls: list[TerraFinCapabilityCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_focus(self, *items: str) -> tuple[str, ...]:
        added: list[str] = []
        existing = set(self.focus_items)
        for item in _dedupe(items):
            if item in existing:
                continue
            existing.add(item)
            self.focus_items.append(item)
            added.append(item)
        return tuple(added)

    def record_artifact(self, artifact: TerraFinArtifact) -> TerraFinArtifact:
        self.artifacts.append(artifact)
        return artifact

    def record_capability_call(
        self,
        capability_name: str,
        *,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
        focus_items: Iterable[str] = (),
        artifacts: Iterable[TerraFinArtifact] = (),
    ) -> TerraFinCapabilityCall:
        record = TerraFinCapabilityCall(
            capability_name=capability_name,
            called_at=_utc_now(),
            inputs=dict(inputs),
            output_keys=tuple(sorted(payload.keys())),
            focus_items=tuple(_dedupe(focus_items)),
            artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
        )
        self.capability_calls.append(record)
        return record

    def snapshot(self) -> TerraFinAgentSessionSnapshot:
        return TerraFinAgentSessionSnapshot(
            session_id=self.session_id,
            focus_items=tuple(self.focus_items),
            artifacts=tuple(self.artifacts),
            capability_calls=tuple(self.capability_calls),
            metadata=dict(self.metadata),
        )
