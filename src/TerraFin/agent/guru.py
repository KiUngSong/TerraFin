"""Hidden guru-router orchestration for TerraFin's main assistant.

The user-facing product surface stays as a single ``TerraFin Agent``. This
module provides deterministic routing rules that let the main orchestrator
invoke hidden investor-persona sessions when the request clearly benefits from
those lenses.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator

from .conversation import TerraFinConversationMessage, make_text_block
from .conversation_state import record_tool_call_history
from .definitions import DEFAULT_HOSTED_AGENT_NAME
from .personas import PersonaRegistry, build_default_persona_registry
from .recovery import RecoveryTracker
from .tools import TerraFinToolDefinition


if TYPE_CHECKING:
    from .conversation import TerraFinHostedConversation
    from .loop import TerraFinHostedAgentLoop


GuruStance = Literal["bullish", "bearish", "neutral", "abstain"]
GuruRouteType = Literal["explicit", "portfolio", "macro", "valuation"]

WARREN_BUFFETT = "warren-buffett"
HOWARD_MARKS = "howard-marks"
STANLEY_DRUCKENMILLER = "stanley-druckenmiller"

_PERSONA_MENTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (WARREN_BUFFETT, r"\b(buffett|warren buffett|oracle of omaha)\b"),
    (HOWARD_MARKS, r"\b(howard marks|oaktree)\b"),
    (STANLEY_DRUCKENMILLER, r"\b(druckenmiller|stanley druckenmiller)\b"),
)

_PORTFOLIO_TERMS = (
    "portfolio",
    "holdings",
    "13f",
    "guru holdings",
    "moat",
    "owner earnings",
    "business quality",
    "quality of the business",
    "margin of safety",
)
_MACRO_TERMS = (
    "macro",
    "liquidity",
    "rates",
    "yield",
    "fed",
    "central bank",
    "regime",
    "dollar",
    "dxy",
    "treasury",
    "inflation",
    "momentum",
    "price action",
    "risk-on",
    "risk off",
)
_VALUATION_TERMS = (
    "valuation",
    "dcf",
    "reverse dcf",
    "intrinsic value",
    "downside",
    "second look",
    "risk premium",
    "cycle",
    "assumptions",
    "deserve a second look",
)
_ANALYSIS_INTENT_TERMS = (
    "how would",
    "stand out",
    "stands out",
    "what stands out",
    "deserve",
    "second look",
    "read on",
    "thesis",
    "main risk",
    "key risk",
    "investor lens",
    "buffett lens",
    "marks lens",
    "druckenmiller lens",
)


@dataclass(frozen=True, slots=True)
class GuruRoutePlan:
    route_type: GuruRouteType
    selected_gurus: tuple[str, ...]
    reason: str
    matched_terms: tuple[str, ...]
    view_context: dict[str, Any] | None = None


class GuruResearchMemo(BaseModel):
    guru: str
    stance: GuruStance
    confidence: int = Field(ge=0, le=100)
    thesis: str = Field(min_length=1)
    key_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)

    @field_validator("key_evidence", "risks", "open_questions", "citations", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


@dataclass(frozen=True, slots=True)
class GuruOrchestratedReply:
    assistant_message: TerraFinConversationMessage
    steps: int
    route_log: dict[str, Any]


_GURU_MEMO_TOOL_NAME = "submit_guru_research_memo"
_GURU_MEMO_TOOL_DESCRIPTION = "Submit the final structured guru research memo after you finish tool-based research."


def maybe_run_guru_orchestrator(
    *,
    loop: "TerraFinHostedAgentLoop",
    session_id: str,
    user_message: str,
    conversation: "TerraFinHostedConversation",
    persona_registry: PersonaRegistry | None = None,
) -> tuple[TerraFinConversationMessage, int, dict[str, Any]] | None:
    registry = persona_registry or build_default_persona_registry()
    route_plan = build_guru_route_plan(
        loop=loop,
        session_id=session_id,
        user_message=user_message,
        persona_registry=registry,
    )
    if route_plan is None:
        return None

    memos: list[GuruResearchMemo] = []
    failures: list[dict[str, str]] = []
    total_steps = 0
    for guru_name in route_plan.selected_gurus:
        memo, steps, failure_reason = _run_guru_research_memo(
            loop=loop,
            parent_session_id=session_id,
            guru_name=guru_name,
            user_message=user_message,
            route_plan=route_plan,
            persona_registry=registry,
        )
        total_steps += steps
        if memo is not None:
            memos.append(memo)
            continue
        failures.append({"guru": guru_name, "reason": failure_reason or "Guru memo generation failed."})

    if not memos:
        history = conversation.metadata.setdefault("guruRouterFailures", [])
        if isinstance(history, list):
            history.append(
                {
                    "createdAt": datetime.now(UTC).isoformat(),
                    "routeType": route_plan.route_type,
                    "selectedGurus": list(route_plan.selected_gurus),
                    "failures": failures,
                }
            )
        if route_plan.route_type == "explicit":
            assistant_message = _build_explicit_guru_failure_reply(
                route_plan=route_plan,
                failures=failures,
                persona_registry=registry,
            )
            route_log = {
                "createdAt": datetime.now(UTC).isoformat(),
                "routeType": route_plan.route_type,
                "reason": route_plan.reason,
                "selectedGurus": list(route_plan.selected_gurus),
                "matchedTerms": list(route_plan.matched_terms),
                "failedGurus": failures,
                "renderMode": "explicit-failure",
            }
            return assistant_message, total_steps, route_log
        return None

    if len(memos) == 1:
        assistant_message = _render_single_guru_memo_reply(
            memo=memos[0],
            route_plan=route_plan,
            persona_registry=registry,
            failures=failures,
        )
        render_mode = "single-memo-direct"
    else:
        assistant_message = _synthesize_memos(
            loop=loop,
            parent_session_id=session_id,
            user_message=user_message,
            conversation=conversation,
            route_plan=route_plan,
            memos=memos,
            persona_registry=registry,
        )
        total_steps += 1
        render_mode = "multi-memo-synthesis"
    route_log = {
        "createdAt": datetime.now(UTC).isoformat(),
        "routeType": route_plan.route_type,
        "reason": route_plan.reason,
        "selectedGurus": list(route_plan.selected_gurus),
        "matchedTerms": list(route_plan.matched_terms),
        "viewContextId": None if route_plan.view_context is None else route_plan.view_context.get("contextId"),
        "pageType": None if route_plan.view_context is None else route_plan.view_context.get("pageType"),
        "memoSummary": [
            {
                "guru": memo.guru,
                "stance": memo.stance,
                "confidence": memo.confidence,
            }
            for memo in memos
        ],
        "failedGurus": failures,
        "renderMode": render_mode,
    }
    return assistant_message, total_steps, route_log


def build_guru_route_plan(
    *,
    loop: "TerraFinHostedAgentLoop",
    session_id: str,
    user_message: str,
    persona_registry: PersonaRegistry | None = None,
) -> GuruRoutePlan | None:
    _ = persona_registry
    normalized_request = _normalize_text(user_message)
    explicit = _explicit_guru_mentions(normalized_request)
    view_context = loop.runtime.read_linked_view_context(session_id)
    normalized_context = _normalize_text(_flatten_view_context(view_context))
    page_type = str(view_context.get("pageType") or "").strip().lower() if view_context.get("available") else ""

    if explicit:
        return GuruRoutePlan(
            route_type="explicit",
            selected_gurus=tuple(explicit[:2]),
            reason="The user explicitly requested named investor perspectives.",
            matched_terms=tuple(explicit),
            view_context=view_context if view_context.get("available") else None,
        )

    if not _analysis_requested(normalized_request, page_type=page_type):
        return None

    portfolio_matches = _matched_terms(normalized_request, normalized_context, _PORTFOLIO_TERMS)
    macro_matches = _matched_terms(normalized_request, normalized_context, _MACRO_TERMS)
    valuation_matches = _matched_terms(normalized_request, normalized_context, _VALUATION_TERMS)

    if page_type == "dcf" or valuation_matches:
        selected = [HOWARD_MARKS]
        if _contains_any(normalized_request, ("moat", "margin of safety", "business quality")):
            selected.append(WARREN_BUFFETT)
        matched_terms = valuation_matches or (["dcf"] if page_type == "dcf" else [])
        return GuruRoutePlan(
            route_type="valuation",
            selected_gurus=tuple(selected[:2]),
            reason="The request is valuation- or downside-oriented, so cycle and risk-premium framing comes first.",
            matched_terms=tuple(matched_terms),
            view_context=view_context if view_context.get("available") else None,
        )

    if page_type == "market-insights" or portfolio_matches:
        selected = [WARREN_BUFFETT]
        if _contains_any(normalized_request, ("risk", "cycle", "downside", "second-level")):
            selected.append(HOWARD_MARKS)
        matched_terms = portfolio_matches or (["market-insights"] if page_type == "market-insights" else [])
        return GuruRoutePlan(
            route_type="portfolio",
            selected_gurus=tuple(selected[:2]),
            reason="The request is about holdings, business quality, or portfolio interpretation.",
            matched_terms=tuple(matched_terms),
            view_context=view_context if view_context.get("available") else None,
        )

    if macro_matches or _macro_chart_context(view_context):
        selected = [STANLEY_DRUCKENMILLER]
        if _contains_any(normalized_request, ("risk", "cycle", "downside", "valuation")):
            selected.append(HOWARD_MARKS)
        matched_terms = macro_matches or (["macro-context"] if _macro_chart_context(view_context) else [])
        return GuruRoutePlan(
            route_type="macro",
            selected_gurus=tuple(selected[:2]),
            reason="The request is macro, regime, or liquidity focused.",
            matched_terms=tuple(matched_terms),
            view_context=view_context if view_context.get("available") else None,
        )

    return None


def _run_guru_research_memo(
    *,
    loop: "TerraFinHostedAgentLoop",
    parent_session_id: str,
    guru_name: str,
    user_message: str,
    route_plan: GuruRoutePlan,
    persona_registry: PersonaRegistry,
) -> tuple[GuruResearchMemo | None, int, str | None]:
    """Run one hidden guru worker and require a structured memo tool call."""
    parent_record = loop.runtime.get_session_record(parent_session_id)
    session_metadata = {
        "hiddenInternal": True,
        "disableGuruRouting": True,
        "parentSessionId": parent_session_id,
        "guruRouteType": route_plan.route_type,
    }
    linked_view_context_id = parent_record.context.session.metadata.get("viewContextId")
    if linked_view_context_id:
        session_metadata["viewContextId"] = linked_view_context_id
    conversation = loop.create_session(
        guru_name,
        metadata=session_metadata,
        allow_internal=True,
    )
    persona = persona_registry.get(guru_name)
    request = _build_guru_research_prompt(
        persona_display_name=persona.display_name,
        user_message=user_message,
        route_plan=route_plan,
        view_context=route_plan.view_context,
    )
    return _execute_guru_worker(
        loop=loop,
        conversation=conversation,
        guru_name=guru_name,
        request=request,
    )


def _build_guru_research_prompt(
    *,
    persona_display_name: str,
    user_message: str,
    route_plan: GuruRoutePlan,
    view_context: Mapping[str, Any] | None,
) -> str:
    lines = [
        f"You are being called as the hidden {persona_display_name} research role inside TerraFin's main orchestrator.",
        "Return research only. Do not provide position sizing, trade execution, or portfolio weights.",
        "",
        f"Route type: {route_plan.route_type}",
        f"User request: {user_message}",
    ]
    if view_context and view_context.get("available"):
        lines.extend(
            [
                "",
                "Current TerraFin view context:",
                json.dumps(
                    {
                        "pageType": view_context.get("pageType"),
                        "title": view_context.get("title"),
                        "summary": view_context.get("summary"),
                        "selection": view_context.get("selection", {}),
                        "entities": view_context.get("entities", []),
                    },
                    ensure_ascii=False,
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"After research is complete, call `{_GURU_MEMO_TOOL_NAME}` exactly once with the final memo payload.",
            "",
            "Rules:",
            "- Cite concrete numbers when available.",
            "- If you lack enough evidence or the case is outside your style, use `abstain`.",
            f"- Do not answer with prose when you are done; finalize with `{_GURU_MEMO_TOOL_NAME}`.",
        ]
    )
    special_guidance = _special_guru_research_guidance(
        persona_display_name=persona_display_name,
        user_message=user_message,
        route_plan=route_plan,
        view_context=view_context,
    )
    if special_guidance:
        lines.extend(["", "Special handling guidance:"])
        lines.extend(f"- {item}" for item in special_guidance)
    return "\n".join(lines)


def _build_guru_memo_tool() -> TerraFinToolDefinition:
    schema = GuruResearchMemo.model_json_schema()
    schema["additionalProperties"] = False
    return TerraFinToolDefinition(
        name=_GURU_MEMO_TOOL_NAME,
        capability_name=_GURU_MEMO_TOOL_NAME,
        description=_GURU_MEMO_TOOL_DESCRIPTION,
        input_schema=schema,
        execution_mode="invoke",
        side_effecting=False,
        metadata={"internalOnly": True, "role": "guruMemo"},
    )


def _validate_guru_memo_arguments(
    *,
    guru_name: str,
    arguments: Mapping[str, Any],
) -> GuruResearchMemo:
    payload = dict(arguments)
    payload["guru"] = guru_name
    return GuruResearchMemo.model_validate(payload)


def _execute_guru_worker(
    *,
    loop: "TerraFinHostedAgentLoop",
    conversation: "TerraFinHostedConversation",
    guru_name: str,
    request: str,
) -> tuple[GuruResearchMemo | None, int, str | None]:
    session_id = conversation.session_id
    loop._ensure_message_budget(conversation, incoming_messages=1)
    user_message = TerraFinConversationMessage(role="user", content=request, blocks=(make_text_block(request),))
    loop._append_conversation_message(conversation, user_message)
    loop._persist_conversation_runtime_state(session_id, conversation)

    memo_tool = _build_guru_memo_tool()
    total_tool_calls = 0
    recovery_budget = RecoveryTracker(loop.recovery_policy)

    for step in range(1, loop.max_steps + 1):
        definition = loop.runtime.get_session_definition(session_id)
        context = loop.runtime.get_session(session_id)
        tools = tuple(loop.tool_adapter.list_tools_for_session(session_id)) + (memo_tool,)
        turn = loop.complete_model_turn(
            agent=definition,
            session=context.session,
            conversation=conversation,
            tools=tools,
        )

        if turn.assistant_message is not None:
            assistant_message = loop._normalize_assistant_message(turn.assistant_message)
            loop._append_conversation_message(conversation, assistant_message)

        if turn.tool_calls:
            loop._append_conversation_message(conversation, loop._build_tool_use_message(turn.tool_calls))
            loop._persist_conversation_runtime_state(session_id, conversation)

        if not turn.tool_calls:
            return None, step, "Guru worker ended without submitting a structured memo."

        record_tool_call_history(conversation, turn.tool_calls)
        loop._persist_conversation_runtime_state(session_id, conversation)

        memo_calls = [tool_call for tool_call in turn.tool_calls if tool_call.tool_name == memo_tool.name]
        non_memo_calls = [tool_call for tool_call in turn.tool_calls if tool_call.tool_name != memo_tool.name]
        if memo_calls:
            if len(memo_calls) != 1 or non_memo_calls:
                return None, step, "Guru worker emitted an invalid mix of memo and capability tool calls."
            try:
                memo = _validate_guru_memo_arguments(
                    guru_name=guru_name,
                    arguments=memo_calls[0].arguments,
                )
            except ValidationError as exc:
                return None, step, f"Guru memo failed validation: {exc}"
            return memo, step, None

        for tool_call in non_memo_calls:
            total_tool_calls += 1
            if total_tool_calls > loop.max_tool_calls:
                return (
                    None,
                    step,
                    (f"Guru worker exceeded max_tool_calls={loop.max_tool_calls} for session '{session_id}'."),
                )
            outcome = loop.tool_execution_engine.execute(session_id, tool_call)
            if outcome.kind == "fatal_error":
                return None, step, str(outcome.error or "Guru tool execution failed.")
            assert outcome.message is not None
            assert outcome.invocation is not None
            loop._append_conversation_message(conversation, outcome.message)
            if outcome.kind == "retryable_error":
                exhausted = recovery_budget.record(outcome.fingerprint)
                if exhausted:
                    return None, step, "Guru worker exhausted its internal tool-recovery budget."
        loop._persist_conversation_runtime_state(session_id, conversation)

    return (
        None,
        loop.max_steps,
        (f"Guru worker exceeded max_steps={loop.max_steps} before submitting a structured memo."),
    )


def _synthesize_memos(
    *,
    loop: "TerraFinHostedAgentLoop",
    parent_session_id: str,
    user_message: str,
    conversation: "TerraFinHostedConversation",
    route_plan: GuruRoutePlan,
    memos: list[GuruResearchMemo],
    persona_registry: PersonaRegistry,
) -> TerraFinConversationMessage:
    parent_record = loop.runtime.get_session_record(parent_session_id)
    definition = loop.runtime.get_agent_definition(DEFAULT_HOSTED_AGENT_NAME)
    prompt = _build_synthesis_prompt(
        user_message=user_message,
        route_plan=route_plan,
        memos=memos,
        persona_registry=persona_registry,
    )
    synthesis_conversation = type(conversation)(
        session_id=f"orchestrator:{uuid4().hex}",
        agent_name=DEFAULT_HOSTED_AGENT_NAME,
        created_at=datetime.now(UTC),
        metadata=dict(parent_record.context.session.metadata),
    )
    system_message = TerraFinConversationMessage(
        role="system",
        content=(
            "You are TerraFin's main orchestrator. Synthesize internal guru research into one user-facing answer. "
            "Do not mention hidden routing mechanics. Present differentiated investor lenses when useful. "
            "Stay research-only and do not give trade sizing or execution instructions."
        ),
    )
    user_turn = TerraFinConversationMessage(role="user", content=prompt)
    synthesis_conversation.messages.extend([system_message, user_turn])
    turn = loop.complete_model_turn(
        agent=definition,
        session=parent_record.context.session,
        conversation=synthesis_conversation,
        tools=(),
    )
    assistant = turn.assistant_message
    if assistant is None or not assistant.content.strip():
        assistant = TerraFinConversationMessage(
            role="assistant",
            content=_fallback_synthesis_text(memos=memos, persona_registry=persona_registry),
        )
    else:
        assistant = loop._normalize_assistant_message(assistant)
    metadata = dict(assistant.metadata)
    metadata.update(
        {
            "guruRouterApplied": True,
            "guruRouteType": route_plan.route_type,
            "selectedGurus": list(route_plan.selected_gurus),
            "memoSummary": [
                {"guru": memo.guru, "stance": memo.stance, "confidence": memo.confidence} for memo in memos
            ],
        }
    )
    return TerraFinConversationMessage(
        role="assistant",
        content=assistant.content,
        name=assistant.name,
        tool_call_id=assistant.tool_call_id,
        metadata=metadata,
    )


def _render_single_guru_memo_reply(
    *,
    memo: GuruResearchMemo,
    route_plan: GuruRoutePlan,
    persona_registry: PersonaRegistry,
    failures: list[dict[str, str]],
) -> TerraFinConversationMessage:
    persona = persona_registry.get(memo.guru)
    stance_text = {
        "bullish": "leans constructive",
        "bearish": "leans cautious",
        "neutral": "leans cautious neutrality",
        "abstain": "would avoid forcing a conclusion",
    }[memo.stance]
    lines = [
        f"From a {persona.display_name} lens, the current read {stance_text}.",
        memo.thesis.strip(),
    ]
    if memo.key_evidence:
        lines.append("")
        lines.append("What drives that view:")
        for item in memo.key_evidence[:3]:
            lines.append(f"- {item}")
    if memo.risks:
        lines.append("")
        lines.append("What would make that lens more careful:")
        for item in memo.risks[:2]:
            lines.append(f"- {item}")
    if memo.open_questions:
        lines.append("")
        lines.append("What this lens would want to verify next:")
        for item in memo.open_questions[:2]:
            lines.append(f"- {item}")
    if memo.citations:
        lines.append("")
        lines.append("Concrete anchors from the research:")
        for item in memo.citations[:2]:
            lines.append(f"- {item}")
    metadata = {
        "guruRouterApplied": True,
        "guruRouteType": route_plan.route_type,
        "selectedGurus": [memo.guru],
        "memoSummary": [
            {
                "guru": memo.guru,
                "stance": memo.stance,
                "confidence": memo.confidence,
            }
        ],
        "guruDirectRender": True,
    }
    if failures:
        metadata["failedGurus"] = list(failures)
    return TerraFinConversationMessage(
        role="assistant",
        content="\n".join(lines),
        metadata=metadata,
    )


def _build_explicit_guru_failure_reply(
    *,
    route_plan: GuruRoutePlan,
    failures: list[dict[str, str]],
    persona_registry: PersonaRegistry,
) -> TerraFinConversationMessage:
    persona_names = [persona_registry.get(name).display_name for name in route_plan.selected_gurus]
    if len(persona_names) == 1:
        subject = persona_names[0]
    else:
        subject = ", ".join(persona_names[:-1]) + f", and {persona_names[-1]}"
    lines = [
        f"I tried to answer this through the {subject} lens, but I couldn't complete that persona-specific research path cleanly.",
        "Rather than pretend with a generic summary, I'm stopping here.",
        "Please retry the question, or narrow it to a ticker, portfolio, or specific page context so I can re-run that investor lens properly.",
    ]
    return TerraFinConversationMessage(
        role="assistant",
        content="\n".join(lines),
        metadata={
            "guruRouterApplied": False,
            "guruRouteType": route_plan.route_type,
            "selectedGurus": list(route_plan.selected_gurus),
            "guruRouterFailure": True,
            "failedGurus": list(failures),
        },
    )


def _build_synthesis_prompt(
    *,
    user_message: str,
    route_plan: GuruRoutePlan,
    memos: list[GuruResearchMemo],
    persona_registry: PersonaRegistry,
) -> str:
    memo_payload = []
    for memo in memos:
        persona = persona_registry.get(memo.guru)
        memo_payload.append(
            {
                "guru": memo.guru,
                "displayName": persona.display_name,
                "stance": memo.stance,
                "confidence": memo.confidence,
                "thesis": memo.thesis,
                "keyEvidence": memo.key_evidence,
                "risks": memo.risks,
                "openQuestions": memo.open_questions,
                "citations": memo.citations,
            }
        )
    return "\n".join(
        [
            f"User request: {user_message}",
            f"Route type: {route_plan.route_type}",
            "Internal guru research memos:",
            json.dumps(memo_payload, ensure_ascii=False, indent=2),
            "",
            "Write one clear TerraFin answer that:",
            "- highlights agreements and disagreements",
            "- attributes ideas as Buffett/Marks/Druckenmiller lenses when useful",
            "- cites concrete evidence from the memos",
            "- stays in research mode and avoids trade sizing",
        ]
    )


def _fallback_synthesis_text(
    *,
    memos: list[GuruResearchMemo],
    persona_registry: PersonaRegistry,
) -> str:
    lines = ["Here is the research read from the investor lenses I applied:"]
    for memo in memos:
        persona = persona_registry.get(memo.guru)
        lines.append("")
        lines.append(f"{persona.display_name}: {memo.thesis}")
        if memo.key_evidence:
            lines.append(f"Key evidence: {memo.key_evidence[0]}")
        if memo.risks:
            lines.append(f"Main risk: {memo.risks[0]}")
    return "\n".join(lines)


def _special_guru_research_guidance(
    *,
    persona_display_name: str,
    user_message: str,
    route_plan: GuruRoutePlan,
    view_context: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    normalized_request = _normalize_text(user_message)
    if not _is_broad_market_request(normalized_request, view_context=view_context):
        return ()

    general = (
        "This is a broad market or index-level question. Broad index ETFs are market containers, not operating businesses.",
        "Do not force company-style moat, owner earnings, or DCF logic onto SPY, QQQ, DIA, VT, or similar broad benchmarks.",
        "Use market-level tools to judge breadth, price behavior, and whether the market appears broadly expensive, fairly priced, euphoric, or fearful.",
    )
    if persona_display_name == "Warren Buffett":
        return general + (
            "A Buffett-style answer should emphasize that he does not make precise macro forecasts and does not treat index ETFs like standalone businesses.",
            "Prefer `market_snapshot` and `market_data` for the broad market. Reserve `valuation`, `fundamental_screen`, and owner-earnings reasoning for actual operating businesses.",
            "Frame the conclusion around valuation discipline, patience, and whether the broad market appears to offer a margin of safety, not around DCF of the index itself.",
        )
    if persona_display_name == "Howard Marks":
        return general + (
            "A Howard Marks answer should focus on cycle position, sentiment, risk appetite, and whether investors are being compensated for risk at the market level.",
            "Use valuation ranges and breadth as cycle clues, not as a substitute for business-level intrinsic value on the index ETF itself.",
        )
    if persona_display_name == "Stanley Druckenmiller":
        return general + (
            "A Druckenmiller answer should focus on liquidity, regime, momentum, and macro asymmetry rather than business-level DCF logic on the index ETF.",
        )
    return general


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _analysis_requested(text: str, *, page_type: str) -> bool:
    if _contains_any(text, _ANALYSIS_INTENT_TERMS):
        return True
    if page_type == "dcf" and _contains_any(
        text, ("assumption", "assumptions", "second look", "deserve", "valuation")
    ):
        return True
    return False


def _matched_terms(request_text: str, context_text: str, terms: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    combined = f"{request_text} {context_text}".strip()
    for term in terms:
        if term in combined and term not in matched:
            matched.append(term)
    return matched


def _explicit_guru_mentions(text: str) -> list[str]:
    selected: list[str] = []
    for guru_name, pattern in _PERSONA_MENTION_PATTERNS:
        if re.search(pattern, text):
            selected.append(guru_name)
    return selected


def _flatten_view_context(view_context: Mapping[str, Any]) -> str:
    if not view_context.get("available"):
        return ""
    parts: list[str] = []

    def _walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if value.strip():
                parts.append(value.strip())
            return
        if isinstance(value, Mapping):
            for item in value.values():
                _walk(item)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        parts.append(str(value))

    _walk(
        {
            "route": view_context.get("route"),
            "pageType": view_context.get("pageType"),
            "title": view_context.get("title"),
            "summary": view_context.get("summary"),
            "selection": view_context.get("selection"),
            "entities": view_context.get("entities"),
        }
    )
    return " ".join(parts)


def _macro_chart_context(view_context: Mapping[str, Any]) -> bool:
    if not view_context.get("available"):
        return False
    if str(view_context.get("pageType") or "").strip().lower() != "chart":
        return False
    context_text = _normalize_text(_flatten_view_context(view_context))
    return _contains_any(context_text, ("dxy", "vix", "tnx", "rates", "yield", "macro"))


def _is_broad_market_request(text: str, *, view_context: Mapping[str, Any] | None) -> bool:
    broad_market_terms = (
        "current market",
        "market status",
        "overall market",
        "broad market",
        "stock market",
        "market environment",
        "market setup",
        "s&p 500",
        "nasdaq",
        "dow",
        "spy",
        "qqq",
        "dia",
        "vt",
        "index",
        "indices",
    )
    if _contains_any(text, broad_market_terms):
        return True
    if not view_context or not view_context.get("available"):
        return False
    page_type = str(view_context.get("pageType") or "").strip().lower()
    if page_type in {"market-insights", "chart"}:
        context_text = _normalize_text(_flatten_view_context(view_context))
        return _contains_any(context_text, broad_market_terms)
    return False


__all__ = [
    "GuruOrchestratedReply",
    "GuruResearchMemo",
    "GuruRoutePlan",
    "build_guru_route_plan",
    "maybe_run_guru_orchestrator",
]
