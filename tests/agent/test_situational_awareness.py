"""Regression tests for P1 desperate-investor-QA fixes.

Covers the four P1 behaviors:

- `build_default_system_prompt` carries the situational-awareness, verbatim-
  citation, and disclosure guidance the orchestrator needs to serve users who
  reveal personal financial context in conversation.
- Persona system prompts carry a confidence-calibration rubric that tells
  personas how to ground high-conviction scores in citations.
- `GuruResearchMemo` clamps `confidence >= 80` with no citations down to 60.
- `sec_filing_section` tool description demands verbatim quoting of risk-factor
  / MD&A language.
"""

from TerraFin.agent.definitions import (
    TerraFinAgentDefinition,
)
from TerraFin.agent.guru import GuruResearchMemo
from TerraFin.agent.loop import build_default_system_prompt
from TerraFin.agent.personas import (
    build_default_persona_registry,
    build_guru_system_prompt,
)
from TerraFin.agent.runtime import build_default_capability_registry


def _plain_definition() -> TerraFinAgentDefinition:
    return TerraFinAgentDefinition(
        name="TerraFin Agent",
        description="The orchestrator agent.",
        allowed_capabilities=("*",),
        metadata={},
    )


def test_default_system_prompt_includes_situational_awareness() -> None:
    prompt = build_default_system_prompt(_plain_definition())

    assert "SITUATIONAL AWARENESS" in prompt
    assert "cost basis" in prompt
    assert "ONE focused follow-up" in prompt
    assert "do not fabricate placeholder values" in prompt


def test_default_system_prompt_includes_sentiment_softening() -> None:
    prompt = build_default_system_prompt(_plain_definition())

    # Emotional-tone guidance lives inside the situational-awareness paragraph.
    assert "anxious" in prompt or "desperate" in prompt
    assert "slow your pace" in prompt


def test_default_system_prompt_demands_verbatim_sec_citations() -> None:
    prompt = build_default_system_prompt(_plain_definition())

    assert "VERBATIM CITATIONS" in prompt
    assert "do NOT paraphrase" in prompt.lower() or "do not paraphrase" in prompt.lower()


def test_default_system_prompt_includes_disclosure_paragraph() -> None:
    prompt = build_default_system_prompt(_plain_definition())

    assert "DISCLOSURE" in prompt
    assert "fiduciary" in prompt
    assert "cannot place trades" in prompt


def test_persona_system_prompt_includes_confidence_rubric() -> None:
    registry = build_default_persona_registry()
    for persona in registry.list():
        prompt = build_guru_system_prompt(persona)
        assert "Confidence Rubric" in prompt, (
            f"persona {persona.name!r} is missing the confidence rubric"
        )
        assert "at least one citation" in prompt, (
            f"persona {persona.name!r} rubric must reference citation requirement"
        )


def test_guru_research_memo_clamps_unsupported_high_confidence() -> None:
    memo = GuruResearchMemo(
        guru="warren-buffett",
        stance="bearish",
        confidence=95,
        thesis="Expensive relative to owner earnings.",
        citations=[],
    )
    assert memo.confidence == 60
    assert "no citations" in memo.thesis.lower()


def test_guru_research_memo_preserves_high_confidence_with_citations() -> None:
    memo = GuruResearchMemo(
        guru="warren-buffett",
        stance="bullish",
        confidence=90,
        thesis="Durable moat with compounding returns.",
        citations=["10-K Item 7 MD&A"],
    )
    assert memo.confidence == 90
    assert memo.thesis == "Durable moat with compounding returns."


def test_guru_research_memo_preserves_modest_confidence_without_citations() -> None:
    memo = GuruResearchMemo(
        guru="howard-marks",
        stance="neutral",
        confidence=55,
        thesis="Cycle position is ambiguous.",
        citations=[],
    )
    # Below the 80 threshold; validator must not tamper with the score.
    assert memo.confidence == 55
    assert memo.thesis == "Cycle position is ambiguous."


def test_sec_filing_section_tool_description_requires_verbatim_citations() -> None:
    registry = build_default_capability_registry(service=None)
    capability = next(
        c for c in registry.list() if c.name == "sec_filing_section"
    )
    description = capability.description
    assert "VERBATIM CITATION RULE" in description
    assert "Do NOT paraphrase" in description
    assert "risk factors" in description.lower()
