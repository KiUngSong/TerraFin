"""Public entry point for orchestrator-driven persona subagent consults.

`run_guru_consult` is what the main TerraFin orchestrator agent calls when
it invokes a `consult_<persona>` tool. It spins up a hidden persona
session, drives it to a structured memo, and returns a JSON-ready dict
that the orchestrator surfaces as the tool result.
"""

from typing import TYPE_CHECKING, Any

from .memo import HOWARD_MARKS, STANLEY_DRUCKENMILLER, WARREN_BUFFETT, GuruRoutePlan
from .personas import PersonaRegistry, build_default_persona_registry
from .worker import _run_guru_research_memo


if TYPE_CHECKING:
    from ..runtime.loop import TerraFinHostedAgentLoop


def run_guru_consult(
    *,
    loop: "TerraFinHostedAgentLoop",
    parent_session_id: str,
    guru_name: str,
    question: str,
    persona_registry: PersonaRegistry | None = None,
) -> dict[str, Any]:
    """Consult one hidden persona subagent and return its structured memo.

    This is the single public entry point for the orchestrator-as-tool
    architecture. The main orchestrator agent calls a
    `consult_<persona>` tool, which dispatches here, which spins up a
    hidden session running the persona-specific research loop and
    returns the persona's `GuruResearchMemo` as a JSON-ready dict for
    the orchestrator to read as its tool_result.

    See `docs/agent/architecture.md#orchestrator--persona-subagents` for
    the authoritative shape.
    """
    registry = persona_registry or build_default_persona_registry()
    try:
        registry.get(guru_name)
    except KeyError:
        return {
            "status": "error",
            "guru": guru_name,
            "reason": f"Unknown persona: {guru_name!r}. "
            f"Valid personas: {WARREN_BUFFETT}, {HOWARD_MARKS}, {STANLEY_DRUCKENMILLER}.",
            "steps": 0,
        }

    view_context = loop.runtime.read_linked_view_context(parent_session_id)
    route_plan = GuruRoutePlan(
        route_type="consult",
        selected_gurus=(guru_name,),
        reason="Consulted by the main orchestrator via tool-call.",
        matched_terms=(),
        view_context=view_context if view_context.get("available") else None,
    )

    memo, steps, failure_reason = _run_guru_research_memo(
        loop=loop,
        parent_session_id=parent_session_id,
        guru_name=guru_name,
        user_message=question,
        route_plan=route_plan,
        persona_registry=registry,
    )

    if memo is None:
        return {
            "status": "failed",
            "guru": guru_name,
            "reason": failure_reason or "The consulted persona could not produce a structured memo.",
            "steps": steps,
        }

    return {
        "status": "ok",
        "guru": guru_name,
        "stance": memo.stance,
        "confidence": memo.confidence,
        "thesis": memo.thesis,
        "keyEvidence": list(memo.key_evidence),
        "risks": list(memo.risks),
        "openQuestions": list(memo.open_questions),
        "citations": list(memo.citations),
        "steps": steps,
    }
