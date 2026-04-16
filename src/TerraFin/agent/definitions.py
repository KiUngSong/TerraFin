from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal


DepthMode = Literal["auto", "recent", "full"]
ChartView = Literal["daily", "weekly", "monthly", "yearly"]
DEFAULT_HOSTED_AGENT_NAME = "terrafin-assistant"
DEFAULT_HOSTED_AGENT_DESCRIPTION = (
    "TerraFin's default hosted agent for market research, macro context, portfolios, "
    "charts, and valuation workflows."
)


@dataclass(frozen=True, slots=True)
class TerraFinAgentDefinition:
    name: str
    description: str
    allowed_capabilities: tuple[str, ...]
    default_depth: DepthMode = "auto"
    default_view: ChartView = "daily"
    chart_access: bool = False
    allow_background_tasks: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def allows(self, capability_name: str) -> bool:
        return "*" in self.allowed_capabilities or capability_name in self.allowed_capabilities


class TerraFinAgentDefinitionRegistry:
    def __init__(self, definitions: Iterable[TerraFinAgentDefinition] | None = None) -> None:
        self._definitions: dict[str, TerraFinAgentDefinition] = {}
        if definitions is not None:
            for definition in definitions:
                self.register(definition)

    def register(self, definition: TerraFinAgentDefinition) -> TerraFinAgentDefinition:
        if definition.name in self._definitions:
            raise ValueError(f"Agent definition already registered: {definition.name}")
        self._definitions[definition.name] = definition
        return definition

    def get(self, name: str) -> TerraFinAgentDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise KeyError(f"Unknown TerraFin agent definition: {name}") from exc

    def list(self) -> tuple[TerraFinAgentDefinition, ...]:
        return tuple(self._definitions.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)


def build_guru_agent_definitions(
    registry: "PersonaRegistry | None" = None,
) -> list[TerraFinAgentDefinition]:
    """Build TerraFinAgentDefinitions for all loaded guru personas."""
    if registry is None:
        from .personas import build_default_persona_registry

        registry = build_default_persona_registry()

    definitions: list[TerraFinAgentDefinition] = []
    for persona in registry.list():
        definitions.append(
            TerraFinAgentDefinition(
                name=persona.name,
                description=persona.description,
                allowed_capabilities=tuple(persona.allowed_capabilities),
                default_depth="auto",
                default_view="daily",
                chart_access=False,
                allow_background_tasks=True,
                metadata={
                    "role": "guru",
                    "visibility": "internal",
                    "investing_style": persona.investing_style,
                    "display_name": persona.display_name,
                    "title": persona.title,
                },
            )
        )
    return definitions


def build_default_agent_definition_registry(
    *,
    include_gurus: bool = False,
) -> TerraFinAgentDefinitionRegistry:
    registry = TerraFinAgentDefinitionRegistry(
        [
            TerraFinAgentDefinition(
                name=DEFAULT_HOSTED_AGENT_NAME,
                description=DEFAULT_HOSTED_AGENT_DESCRIPTION,
                allowed_capabilities=("*",),
                default_depth="auto",
                default_view="daily",
                chart_access=True,
                allow_background_tasks=True,
                metadata={"role": "default", "visibility": "public"},
            ),
        ]
    )
    if include_gurus:
        for definition in build_guru_agent_definitions():
            registry.register(definition)
    return registry


def is_internal_agent_definition(definition: TerraFinAgentDefinition) -> bool:
    return str(definition.metadata.get("visibility", "public")).strip().lower() == "internal"
