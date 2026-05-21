"""TerraFinAgentContext + create_agent_context factory.

Top of the runtime data layer: composes a capability registry, a session,
and a task registry into a single mutable context that handlers receive.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .artifacts import TerraFinArtifact, TerraFinCapabilityCall
from .capability import TerraFinCapability, TerraFinCapabilityRegistry, build_default_capability_registry
from .session import TerraFinAgentSession
from .tasks import TerraFinTaskRecord, TerraFinTaskRegistry


if TYPE_CHECKING:
    from ..service import TerraFinAgentService


@dataclass
class TerraFinAgentContext:
    registry: TerraFinCapabilityRegistry
    session: TerraFinAgentSession = field(default_factory=TerraFinAgentSession)
    task_registry: TerraFinTaskRegistry = field(default_factory=TerraFinTaskRegistry)
    service: "TerraFinAgentService | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def call(self, capability_name: str, /, **kwargs: Any) -> dict[str, Any]:
        return self.registry.invoke(capability_name, context=self, **kwargs)

    def run_task(
        self,
        capability_name: str,
        /,
        *,
        description: str | None = None,
        **kwargs: Any,
    ) -> tuple[TerraFinTaskRecord, dict[str, Any]]:
        task = self.task_registry.create(
            capability_name,
            description=description or capability_name.replace("_", " "),
            session_id=self.session.session_id,
            input_payload=kwargs,
        )
        self.task_registry.mark_running(task.task_id)
        try:
            result = self.call(capability_name, **kwargs)
        except Exception as exc:
            self.task_registry.fail(task.task_id, error=str(exc))
            raise
        completed = self.task_registry.complete(task.task_id, result=result)
        return completed, result

    def _record_capability_result(
        self,
        capability: TerraFinCapability,
        *,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> TerraFinCapabilityCall:
        focus_items = capability.extract_focus(inputs, payload)
        if focus_items:
            self.session.record_focus(*focus_items)

        artifacts: list[TerraFinArtifact] = []
        artifact = capability.build_artifact(self.session.session_id, inputs, payload)
        if artifact is not None:
            self.session.record_artifact(artifact)
            artifacts.append(artifact)

        return self.session.record_capability_call(
            capability.name,
            inputs=inputs,
            payload=payload,
            focus_items=focus_items,
            artifacts=artifacts,
        )


def create_agent_context(
    *,
    service: "TerraFinAgentService | None" = None,
    registry: TerraFinCapabilityRegistry | None = None,
    session: TerraFinAgentSession | None = None,
    task_registry: TerraFinTaskRegistry | None = None,
    chart_opener: Callable[..., dict[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TerraFinAgentContext:
    from ..service import TerraFinAgentService

    resolved_service = service or TerraFinAgentService()
    resolved_registry = registry or build_default_capability_registry(
        resolved_service,
        chart_opener=chart_opener,
    )
    return TerraFinAgentContext(
        registry=resolved_registry,
        session=session or TerraFinAgentSession(),
        task_registry=task_registry or TerraFinTaskRegistry(),
        service=resolved_service,
        metadata=dict(metadata or {}),
    )
