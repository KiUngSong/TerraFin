"""Guru persona definitions for TerraFin agent sessions.

Each persona is a YAML file in this directory that defines an investor's
identity, philosophy, quotes, decision framework, and capability restrictions.
The PersonaRegistry loads all YAML files at construction time and exposes
them by name.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class PersonaQuote:
    source: str
    text: str


@dataclass(frozen=True, slots=True)
class DecisionFramework:
    bullish: str
    bearish: str
    neutral: str


@dataclass(frozen=True, slots=True)
class GuruPersona:
    name: str
    display_name: str
    title: str
    description: str
    investing_style: str
    voice: str
    allowed_capabilities: tuple[str, ...]
    principles: tuple[str, ...]
    decision_framework: DecisionFramework
    quotes: tuple[PersonaQuote, ...]
    known_biases: tuple[str, ...]
    time_horizon: str = ""
    abstain_conditions: tuple[str, ...] = ()
    evidence_priority: tuple[str, ...] = ()
    missing_data_behavior: str = ""
    thesis_invalidation_rules: tuple[str, ...] = ()
    sell_discipline: tuple[str, ...] = ()
    disagreement_policy: str = ""
    style_exemplars: tuple[str, ...] = ()
    recent_context_cues: tuple[str, ...] = ()
    broad_market_playbook: tuple[str, ...] = ()
    forbidden_backbone_evidence: tuple[str, ...] = ()
    signature_concepts: tuple[str, ...] = ()
    confidence_rubric: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def _parse_persona(raw: dict[str, Any]) -> GuruPersona:
    framework_raw = raw.get("decision_framework", {})
    return GuruPersona(
        name=raw["name"],
        display_name=raw["display_name"],
        title=raw.get("title", ""),
        description=raw.get("description", "").strip(),
        investing_style=raw.get("investing_style", ""),
        voice=raw.get("voice", ""),
        allowed_capabilities=tuple(raw.get("allowed_capabilities", ())),
        principles=tuple(raw.get("principles", ())),
        decision_framework=DecisionFramework(
            bullish=framework_raw.get("bullish", ""),
            bearish=framework_raw.get("bearish", ""),
            neutral=framework_raw.get("neutral", ""),
        ),
        quotes=tuple(
            PersonaQuote(source=q.get("source", ""), text=q.get("text", ""))
            for q in raw.get("quotes", ())
        ),
        known_biases=tuple(raw.get("known_biases", ())),
        time_horizon=raw.get("time_horizon", ""),
        abstain_conditions=tuple(raw.get("abstain_conditions", ())),
        evidence_priority=tuple(raw.get("evidence_priority", ())),
        missing_data_behavior=raw.get("missing_data_behavior", ""),
        thesis_invalidation_rules=tuple(raw.get("thesis_invalidation_rules", ())),
        sell_discipline=tuple(raw.get("sell_discipline", ())),
        disagreement_policy=raw.get("disagreement_policy", ""),
        style_exemplars=tuple(raw.get("style_exemplars", ())),
        recent_context_cues=tuple(raw.get("recent_context_cues", ())),
        broad_market_playbook=tuple(raw.get("broad_market_playbook", ())),
        forbidden_backbone_evidence=tuple(raw.get("forbidden_backbone_evidence", ())),
        signature_concepts=tuple(raw.get("signature_concepts", ())),
        confidence_rubric=tuple(raw.get("confidence_rubric", ())),
        metadata=dict(raw.get("metadata", {})),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class PersonaRegistry:
    """Loads and serves guru persona definitions from YAML files."""

    def __init__(self, personas: dict[str, GuruPersona] | None = None) -> None:
        self._personas: dict[str, GuruPersona] = dict(personas or {})

    def register(self, persona: GuruPersona) -> GuruPersona:
        if persona.name in self._personas:
            raise ValueError(f"Persona already registered: {persona.name}")
        self._personas[persona.name] = persona
        return persona

    def get(self, name: str) -> GuruPersona:
        try:
            return self._personas[name]
        except KeyError as exc:
            raise KeyError(f"Unknown guru persona: {name}") from exc

    def list(self) -> tuple[GuruPersona, ...]:
        return tuple(self._personas.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._personas)


def _personas_directory() -> Path:
    """Return the path to the directory containing persona YAML files."""
    return Path(__file__).parent


def build_default_persona_registry() -> PersonaRegistry:
    """Scan the personas directory for YAML files and load all of them."""
    directory = _personas_directory()
    registry = PersonaRegistry()
    for yaml_path in sorted(directory.glob("*.yaml")):
        raw = _load_yaml(yaml_path)
        if "name" not in raw:
            continue
        persona = _parse_persona(raw)
        registry.register(persona)
    return registry


def build_guru_system_prompt(persona: GuruPersona) -> str:
    """Compose a persona YAML into a full system prompt for the agent loop."""
    lines: list[str] = []

    lines.append(f'You are {persona.display_name}, "{persona.title}".')
    lines.append("")
    lines.append(persona.description)
    lines.append("")

    lines.append("## Your Investment Philosophy")
    for i, principle in enumerate(persona.principles, 1):
        lines.append(f"{i}. {principle}")
    lines.append("")

    fw = persona.decision_framework
    lines.append("## Your Decision Framework")
    lines.append(f"- **Bullish** when: {fw.bullish}")
    lines.append(f"- **Bearish** when: {fw.bearish}")
    lines.append(f"- **Neutral** when: {fw.neutral}")
    lines.append("")

    lines.append("## Your Voice")
    lines.append(persona.voice)
    if persona.quotes:
        lines.append("")
        lines.append("When reasoning, channel these perspectives:")
        for quote in persona.quotes[:4]:
            lines.append(f'- "{quote.text.strip()}" — {quote.source}')
    lines.append("")

    if persona.known_biases:
        lines.append("## Your Known Biases (be self-aware)")
        for bias in persona.known_biases:
            lines.append(f"- {bias}")
        lines.append("")

    if persona.time_horizon:
        lines.append("## Time Horizon")
        lines.append(persona.time_horizon)
        lines.append("")

    if persona.evidence_priority:
        lines.append("## Evidence Priority")
        for item in persona.evidence_priority:
            lines.append(f"- {item}")
        lines.append("")

    if persona.abstain_conditions:
        lines.append("## Abstain Conditions")
        for item in persona.abstain_conditions:
            lines.append(f"- {item}")
        lines.append("")

    if persona.missing_data_behavior:
        lines.append("## Missing Data Behavior")
        lines.append(persona.missing_data_behavior)
        lines.append("")

    if persona.thesis_invalidation_rules:
        lines.append("## Thesis Invalidation Rules")
        for item in persona.thesis_invalidation_rules:
            lines.append(f"- {item}")
        lines.append("")

    if persona.sell_discipline:
        lines.append("## Sell Discipline")
        for item in persona.sell_discipline:
            lines.append(f"- {item}")
        lines.append("")

    if persona.disagreement_policy:
        lines.append("## Disagreement Policy")
        lines.append(persona.disagreement_policy)
        lines.append("")

    if persona.style_exemplars:
        lines.append("## Style Exemplars")
        for item in persona.style_exemplars:
            lines.append(f"- {item}")
        lines.append("")

    if persona.recent_context_cues:
        lines.append("## Recent Context Cues")
        for item in persona.recent_context_cues:
            lines.append(f"- {item}")
        lines.append("")

    if persona.broad_market_playbook:
        lines.append("## Broad Market Playbook")
        for item in persona.broad_market_playbook:
            lines.append(f"- {item}")
        lines.append("")

    if persona.signature_concepts:
        lines.append("## Signature Concepts")
        for item in persona.signature_concepts:
            lines.append(f"- {item}")
        lines.append("")

    if persona.forbidden_backbone_evidence:
        lines.append("## Evidence To Avoid As The Main Backbone")
        for item in persona.forbidden_backbone_evidence:
            lines.append(f"- {item}")
        lines.append("")

    if persona.confidence_rubric:
        lines.append("## Confidence Rubric (0-100)")
        lines.append(
            "Calibrate your `confidence` score honestly against this rubric. "
            "If you are citing nothing from tool results, your confidence must not exceed 60 — "
            "an unsupported opinion is not a high-confidence one."
        )
        for item in persona.confidence_rubric:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## Available Tools")
    lines.append(f"You have access to: {', '.join(persona.allowed_capabilities)}")
    lines.append("")

    lines.append("## Rules")
    lines.append("- Use TerraFin tools to gather data before forming opinions.")
    lines.append("- Never invent financial data. If a tool doesn't return what you need, say so.")
    lines.append("- When providing analysis, cite specific numbers from tool results.")
    lines.append("- Your reasoning should reflect your philosophy — not generic financial advice.")
    lines.append("- If the question depends on the user's current TerraFin page, use `current_view_context` before guessing.")
    lines.append("- Stay in research mode. Do not produce position sizing or trade execution instructions.")

    return "\n".join(lines)


__all__ = [
    "DecisionFramework",
    "GuruPersona",
    "PersonaQuote",
    "PersonaRegistry",
    "build_default_persona_registry",
    "build_guru_system_prompt",
]
