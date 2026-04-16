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

from .conversation import TerraFinConversationMessage, make_text_block, make_tool_result_block
from .conversation_state import record_tool_call_history
from .definitions import DEFAULT_HOSTED_AGENT_NAME
from .personas import GuruPersona, PersonaRegistry, build_default_persona_registry
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
    (HOWARD_MARKS, r"\b(howard marks|marks|oaktree)\b"),
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
_COMPARISON_TERMS = (
    "disagree",
    "difference",
    "different",
    "compare",
    "comparison",
    "versus",
    "vs",
    "debate",
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

    if _should_direct_render_multi_guru(user_message=user_message, route_plan=route_plan):
        assistant_message = _render_multi_guru_comparison_reply(
            memos=memos,
            route_plan=route_plan,
            persona_registry=registry,
            failures=failures,
        )
        render_mode = "multi-memo-direct"
    elif len(memos) == 1:
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
            selected_gurus=tuple(explicit[:3]),
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
        persona=persona,
        persona_display_name=persona.display_name,
        user_message=user_message,
        route_plan=route_plan,
        view_context=route_plan.view_context,
    )
    return _execute_guru_worker(
        loop=loop,
        conversation=conversation,
        persona=persona,
        route_plan=route_plan,
        guru_name=guru_name,
        request=request,
    )


def _build_guru_research_prompt(
    *,
    persona: GuruPersona,
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
            f"`{_GURU_MEMO_TOOL_NAME}` must include: stance, confidence, thesis, key_evidence, risks, open_questions, citations.",
            (
                "Memo payload example: "
                "{\"stance\":\"neutral\",\"confidence\":72,\"thesis\":\"...\","
                "\"key_evidence\":[\"...\"],\"risks\":[\"...\"],"
                "\"open_questions\":[\"...\"],\"citations\":[\"...\"]}"
            ),
            "",
            "Rules:",
            "- Cite concrete numbers when available.",
            "- If you lack enough evidence or the case is outside your style, use `abstain`.",
            "- If some supporting inputs are missing but you still have enough to frame the lens honestly, submit a lower-confidence partial memo in character instead of a sterile refusal.",
            f"- Do not answer with prose when you are done; finalize with `{_GURU_MEMO_TOOL_NAME}`.",
            "- Your memo must sound like this investor's actual worldview, not a generic analyst summary with a famous name swapped in.",
            "- Open the thesis with one unmistakable worldview sentence before you elaborate on supporting evidence.",
            "- Key evidence and risks should be clean, complete, investor-readable bullets. Prefer two strong bullets to five messy ones.",
            "- Keep open_questions plain, concrete, and investor-readable. They should read like real follow-up questions, not fragments or word salad.",
            f"- The final thesis must explicitly reflect native concepts from this investor's worldview, such as: {', '.join(persona.signature_concepts[:4])}.",
        ]
    )
    special_guidance = _special_guru_research_guidance(
        persona=persona,
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
    persona: GuruPersona,
    route_plan: GuruRoutePlan,
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
    persona_fit_retry_used = False
    memo_validation_retry_used = False
    finalize_reminder_used = False
    broad_market = _is_broad_market_request(_normalize_text(request), view_context=route_plan.view_context)

    for step in range(1, loop.max_steps + 1):
        definition = loop.runtime.get_session_definition(session_id)
        context = loop.runtime.get_session(session_id)
        tools = _select_guru_worker_tools(
            loop=loop,
            session_id=session_id,
            persona=persona,
            broad_market=broad_market,
            memo_tool=memo_tool,
        )
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
                if memo_validation_retry_used:
                    return None, step, f"Guru memo failed validation: {exc}"
                retry_prompt = (
                    f"Your `{_GURU_MEMO_TOOL_NAME}` call was malformed. "
                    "Retry it once with all required fields present: stance, confidence, thesis, key_evidence, "
                    "risks, open_questions, citations. "
                    f"Validation details: {exc}"
                )
                loop._append_conversation_message(
                    conversation,
                    TerraFinConversationMessage(
                        role="user",
                        content=retry_prompt,
                        blocks=(make_text_block(retry_prompt),),
                        metadata={"internalOnly": True, "guruMemoValidationRetry": True},
                    ),
                )
                loop._persist_conversation_runtime_state(session_id, conversation)
                memo_validation_retry_used = True
                continue
            fit_feedback = _persona_fit_feedback(
                persona=persona,
                route_plan=route_plan,
                memo=memo,
            )
            if fit_feedback:
                if persona_fit_retry_used:
                    return None, step, f"Guru memo still failed persona-fit review: {fit_feedback}"
                retry_prompt = (
                    f"Rewrite the memo so it actually sounds like {persona.display_name}. "
                    f"Current issue: {fit_feedback} "
                    "Do not switch to generic analyst language. Keep the memo grounded in this investor's worldview and signature concepts."
                )
                loop._append_conversation_message(
                    conversation,
                    TerraFinConversationMessage(
                        role="user",
                        content=retry_prompt,
                        blocks=(make_text_block(retry_prompt),),
                        metadata={"internalOnly": True, "guruPersonaFitRetry": True},
                    ),
                )
                loop._persist_conversation_runtime_state(session_id, conversation)
                persona_fit_retry_used = True
                continue
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
            loop._append_conversation_message(
                conversation,
                _sanitize_guru_tool_message(
                    persona=persona,
                    broad_market=broad_market,
                    tool_call=tool_call,
                    invocation=outcome.invocation,
                    message=outcome.message,
                ),
            )
            if outcome.kind == "retryable_error":
                exhausted = recovery_budget.record(outcome.fingerprint)
                if exhausted:
                    return None, step, "Guru worker exhausted its internal tool-recovery budget."
        loop._persist_conversation_runtime_state(session_id, conversation)
        if broad_market and total_tool_calls >= 3 and not finalize_reminder_used:
            finalize_prompt = (
                "You already have enough evidence for a compact memo in this investor's voice. "
                f"Do not keep gathering benchmarks unless a single critical gap remains. On the next turn, either call `{_GURU_MEMO_TOOL_NAME}` "
                "or abstain cleanly."
            )
            loop._append_conversation_message(
                conversation,
                TerraFinConversationMessage(
                    role="user",
                    content=finalize_prompt,
                    blocks=(make_text_block(finalize_prompt),),
                    metadata={"internalOnly": True, "guruFinalizeReminder": True},
                ),
            )
            loop._persist_conversation_runtime_state(session_id, conversation)
            finalize_reminder_used = True

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
    lines = _persona_render_lines(persona=persona, memo=memo)
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
    if len(route_plan.selected_gurus) == 1:
        persona = persona_registry.get(route_plan.selected_gurus[0])
        lines = _persona_partial_failure_lines(persona=persona, route_plan=route_plan)
        lines.extend(
            [
                "",
                "I could not complete the full persona-specific research path cleanly this turn, so treat this as a low-confidence partial read rather than a finished memo.",
                "If you retry with a tighter ticker, portfolio, or page-specific context, I can usually produce a much sharper version of this lens.",
            ]
        )
        return TerraFinConversationMessage(
            role="assistant",
            content="\n".join(lines),
            metadata={
                "guruRouterApplied": True,
                "guruRouteType": route_plan.route_type,
                "selectedGurus": list(route_plan.selected_gurus),
                "guruRouterFailure": True,
                "guruRouterPartial": True,
                "failedGurus": list(failures),
            },
        )

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


def _persona_partial_failure_lines(
    *,
    persona: GuruPersona,
    route_plan: GuruRoutePlan,
) -> list[str]:
    broad_market = route_plan.route_type in {"explicit", "macro"} and _is_broad_market_request(
        _normalize_text(" ".join(route_plan.matched_terms) + " " + route_plan.reason),
        view_context=route_plan.view_context,
    )
    if persona.name == WARREN_BUFFETT:
        lines = [
            f"From a {persona.display_name} lens, the default instinct is still patience rather than activity.",
            "If the broad market is not offering a clear margin of safety, cash and optionality matter more than having an opinion every day.",
        ]
        if not broad_market:
            lines[1] = "If the business quality and price discipline cannot both be defended cleanly, the right move is usually to wait rather than stretch."
        return lines
    if persona.name == HOWARD_MARKS:
        return [
            f"From a {persona.display_name} lens, the first question is still where we are in the cycle and whether investors are being paid enough for the risk they are taking.",
            "Even without a finished memo, the default read is caution when optimism outruns compensation for risk and psychology gets friendlier than the payoff warrants.",
        ]
    if persona.name == STANLEY_DRUCKENMILLER:
        lines = [
            f"From a {persona.display_name} lens, the broad-market issue is still the macro tradeoff between liquidity, rates, and what the tape is confirming.",
            "If that tradeoff is messy rather than one-way, the cleaner edge is often in selective stocks or sectors, not in pretending the index has a perfect setup.",
        ]
        if not broad_market:
            lines[1] = "If the macro tailwind and price confirmation are not lining up cleanly, this is usually a low-edge setup rather than a bet to press."
        return lines
    return [
        f"From a {persona.display_name} lens, the right move is to avoid pretending the evidence is cleaner than it is.",
    ]


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
    persona: GuruPersona,
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
        "For SPY, QQQ, DIA, VT, or other equity benchmarks, use market_snapshot, market_data, risk_profile, valuation, and economic rather than free-form macro_focus guesses.",
        "Use economic with canonical names such as Federal Funds Effective Rate, Treasury-10Y, M2, or SOMA instead of improvising descriptive macro labels.",
        "If you need economic series, use canonical names like Federal Funds Effective Rate, Unemployment Rate, M2, or SOMA rather than free-form prose labels.",
        "Do not call company_info, earnings, financials, or fundamental_screen on SPY, QQQ, DIA, VT, or similar benchmark ETFs.",
        "You do not need an exhaustive research pass here. Prefer a compact 2-4 tool plan, then finalize the memo instead of collecting every possible datapoint.",
        "A good broad-market sequence is: one or two market_snapshot or risk_profile checks on the main benchmarks, then at most one or two macro or economic context checks, then finalize.",
        "Do not use `resolve` for broad-market questions. It is not a web search substitute and usually just burns steps without improving the memo.",
    )
    persona_guidance: tuple[str, ...] = tuple(persona.broad_market_playbook)
    recent_cues: tuple[str, ...] = tuple(
        f"Recent cue to reflect if relevant: {item}" for item in persona.recent_context_cues[:3]
    )
    forbidden: tuple[str, ...] = tuple(
        f"Avoid making this the backbone of the answer: {item}" for item in persona.forbidden_backbone_evidence
    )
    if persona_display_name == "Warren Buffett":
        return general + (
            "If you use valuation on a broad market ETF, use it only as a rough temperature check on relative expensiveness; do not make missing DCF or owner-earnings data for the ETF shell the main point.",
            "For Buffett on the broad market, patience, cash, and the absence of clear margin of safety should dominate the memo more than any indicator reading.",
        ) + persona_guidance + recent_cues + forbidden
    if persona_display_name == "Howard Marks":
        return general + (
            "For Howard Marks, you only need enough evidence to judge cycle position, investor psychology, and risk compensation. Do not burn steps trying to build a full macro dashboard.",
            "If breadth, sentiment, and valuation already point to optimism or compressed risk premium, finalize the memo rather than continuing to hunt for every confirming statistic.",
            "Your opening sentence should sound like a cycle-and-psychology investor, not a chart technician or economist pretending to be Howard Marks.",
        ) + persona_guidance + recent_cues + forbidden
    if persona_display_name == "Stanley Druckenmiller":
        return general + (
            "For Druckenmiller, broad-market questions should usually weigh growth, liquidity, and yields first; technical stretch can support the read, but it should not dominate the opening thesis.",
            "Your opening sentence should sound like a macro trader weighing rates, liquidity, earnings, and tape confirmation.",
            "For a U.S. equity-market setup, focus on SPY and QQQ first. Do not fan out into DIA or VT unless they add something essential.",
            "After roughly three useful tool calls, stop gathering and finalize the memo. This style should act on the tradeoff, not build a giant dashboard.",
        ) + persona_guidance + recent_cues + forbidden
    return general + persona_guidance + recent_cues + forbidden


def _select_guru_worker_tools(
    *,
    loop: "TerraFinHostedAgentLoop",
    session_id: str,
    persona: GuruPersona,
    broad_market: bool,
    memo_tool: TerraFinToolDefinition,
) -> tuple[TerraFinToolDefinition, ...]:
    tools = [
        tool
        for tool in loop.tool_adapter.list_tools_for_session(session_id)
        if tool.execution_mode == "invoke" and not (broad_market and tool.name == "resolve")
    ]
    if broad_market:
        allowed_by_persona: dict[str, set[str]] = {
            WARREN_BUFFETT: {"market_snapshot", "valuation", "current_view_context"},
            HOWARD_MARKS: {"market_snapshot", "valuation", "economic", "current_view_context"},
            STANLEY_DRUCKENMILLER: {
                "market_snapshot",
                "economic",
                "risk_profile",
                "current_view_context",
            },
        }
        allowed = allowed_by_persona.get(persona.name)
        if allowed is not None:
            tools = [tool for tool in tools if tool.capability_name in allowed]
    return tuple(tools) + (memo_tool,)


def _sanitize_guru_tool_message(
    *,
    persona: GuruPersona,
    broad_market: bool,
    tool_call: Any,
    invocation: Any,
    message: TerraFinConversationMessage,
) -> TerraFinConversationMessage:
    if invocation.is_error:
        return message

    payload = dict(invocation.payload or {})
    ticker = str(payload.get("ticker") or payload.get("name") or "").upper()
    benchmark_ticker = ticker in {"SPY", "QQQ", "DIA", "VT", "IWM"}

    filtered_payload: dict[str, Any] | None = None
    if broad_market and benchmark_ticker and persona.name in {WARREN_BUFFETT, HOWARD_MARKS, STANLEY_DRUCKENMILLER} and tool_call.tool_name == "market_snapshot":
        filtered_payload = {
            "ticker": payload.get("ticker"),
            "price_action": payload.get("price_action"),
            "market_breadth": payload.get("market_breadth"),
            "processing": payload.get("processing"),
        }
    elif persona.name == WARREN_BUFFETT and tool_call.tool_name == "valuation":
        filtered_payload = {
            "ticker": payload.get("ticker"),
            "dcf": payload.get("dcf"),
            "relative": payload.get("relative"),
            "current_price": payload.get("current_price"),
            "margin_of_safety_pct": payload.get("margin_of_safety_pct"),
            "processing": payload.get("processing"),
        }
    elif broad_market and benchmark_ticker and persona.name == HOWARD_MARKS and tool_call.tool_name == "valuation":
        filtered_payload = {
            "ticker": payload.get("ticker"),
            "relative": payload.get("relative"),
            "current_price": payload.get("current_price"),
            "margin_of_safety_pct": payload.get("margin_of_safety_pct"),
            "processing": payload.get("processing"),
        }
    elif broad_market and benchmark_ticker and persona.name == STANLEY_DRUCKENMILLER and tool_call.tool_name == "risk_profile":
        filtered_payload = {
            "ticker": payload.get("ticker"),
            "tail_risk": payload.get("tail_risk"),
            "volatility": payload.get("volatility"),
            "drawdown": payload.get("drawdown"),
            "processing": payload.get("processing"),
        }

    if filtered_payload is None:
        return message

    content_payload = {
        "toolName": invocation.tool_name,
        "capabilityName": invocation.capability_name,
        "executionMode": invocation.execution_mode,
        "payload": filtered_payload,
    }
    if invocation.task is not None:
        content_payload["task"] = {
            "taskId": invocation.task.task_id,
            "status": invocation.task.status,
            "description": invocation.task.description,
        }

    metadata = dict(message.metadata)
    metadata["guruSanitized"] = True
    return TerraFinConversationMessage(
        role="tool",
        name=tool_call.tool_name,
        tool_call_id=tool_call.call_id,
        content=json.dumps(content_payload, ensure_ascii=False, separators=(",", ":")),
        metadata=metadata,
        blocks=(
            make_tool_result_block(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                capability_name=invocation.capability_name,
                execution_mode=invocation.execution_mode,
                payload=filtered_payload,
                task=None
                if invocation.task is None
                else {
                    "taskId": invocation.task.task_id,
                    "status": invocation.task.status,
                    "description": invocation.task.description,
                },
                is_error=invocation.is_error,
                retryable=invocation.retryable,
                error_code=invocation.error_code,
                error_message=invocation.error_message,
            ),
        ),
    )


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
        "market cycle",
        "overall market",
        "broad market",
        "stock market",
        "market environment",
        "market setup",
        "equity market",
        "market trade",
        "where are we in the cycle",
        "the cycle right now",
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


def _persona_fit_feedback(
    *,
    persona: GuruPersona,
    route_plan: GuruRoutePlan,
    memo: GuruResearchMemo,
) -> str | None:
    thesis = _normalize_text(memo.thesis)
    combined = _normalize_text(
        " ".join(
            [
                memo.thesis,
                *memo.key_evidence,
                *memo.risks,
                *memo.open_questions,
                *memo.citations,
            ]
        )
    )
    technical_terms = ("rsi", "bollinger", "macd", "upper band", "overbought")
    technical_hits = sum(1 for term in technical_terms if term in combined)
    signature_hits = sum(1 for term in persona.signature_concepts if term.lower() in combined)
    broad_market = _is_broad_market_request(
        _normalize_text(" ".join(route_plan.matched_terms) + " " + route_plan.reason),
        view_context=route_plan.view_context,
    ) or route_plan.route_type in {"explicit", "macro"}

    if broad_market and technical_hits >= 2 and signature_hits == 0:
        return (
            "The memo relies on shared technical-analysis language but does not surface this investor's signature concepts."
        )
    narrative_feedback = _narrative_quality_feedback([memo.thesis, *memo.key_evidence, *memo.risks])
    if narrative_feedback:
        return narrative_feedback
    question_feedback = _open_question_quality_feedback(memo.open_questions)
    if question_feedback:
        return question_feedback
    if persona.name == WARREN_BUFFETT:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("business", "businesses", "owner", "price", "valuation", "wonderful business"),
            secondary_terms=("margin of safety", "patience", "cash", "optionality"),
            failure_text="A Buffett memo should open from the perspective of a long-term business owner and price discipline, not just valuation math.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and technical_hits >= 1 and technical_hits >= max(signature_hits, 1):
            return "A Buffett broad-market answer cannot lean on RSI, MACD, or short-term tape language as primary evidence."
        if broad_market and signature_hits == 0:
            return "A Buffett broad-market answer should sound patient, valuation-disciplined, and anchored in margin of safety or cash/optionality."
    if persona.name == HOWARD_MARKS:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("cycle", "pendulum", "psychology", "optimism", "fear", "euphoria"),
            secondary_terms=("risk premium", "paid enough for the risk", "second-level", "prepare"),
            failure_text="A Howard Marks memo should sound like cycle position, psychology, and risk compensation are the center of gravity.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and signature_hits == 0:
            return "A Howard Marks answer should foreground cycle position, psychology, risk premium, or second-level thinking."
    if persona.name == STANLEY_DRUCKENMILLER:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("liquidity", "rates", "yield", "bond yields", "macro tradeoff"),
            secondary_terms=("earnings", "tape", "animal spirits", "individual stock", "edge"),
            failure_text="A Druckenmiller memo should open with the macro tradeoff between rates/liquidity and what earnings or the tape are saying.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and memo.stance == "abstain":
            return "A Druckenmiller broad-market answer should usually weigh the macro tradeoff explicitly instead of defaulting to abstain."
        if broad_market and signature_hits == 0:
            return "A Druckenmiller answer should sound macro-driven, with liquidity, yields, growth, animal spirits, or stock-selection tradeoffs."
    return None


def _worldview_sentence_feedback(
    *,
    thesis: str,
    combined: str,
    primary_terms: tuple[str, ...],
    secondary_terms: tuple[str, ...],
    failure_text: str,
) -> str | None:
    if not any(term in thesis for term in primary_terms):
        return failure_text
    if not any(term in combined for term in secondary_terms):
        return failure_text
    return None


def _open_question_quality_feedback(open_questions: list[str]) -> str | None:
    allowed_starts = {
        "what",
        "which",
        "whether",
        "how",
        "why",
        "will",
        "would",
        "could",
        "can",
        "is",
        "are",
        "should",
        "do",
        "does",
        "to",
        "where",
        "when",
        "if",
    }
    for question in open_questions:
        normalized = _normalize_text(question)
        if not normalized:
            continue
        words = normalized.split()
        if len(words) > 30:
            return "The memo's open questions should stay plain and concrete rather than sprawling or fragmentary."
        if any(marker in question for marker in ("[[", "]]", "{{", "}}", "__", "]]>", "<![", "=>")):
            return "The memo's open questions should read like real investor follow-up questions, not fragments."
        if words[0] not in allowed_starts and len(words) <= 4:
            return "The memo's open questions should read like real investor follow-up questions, not fragments."
    return None


def _narrative_quality_feedback(texts: list[str]) -> str | None:
    severe_garble = re.compile(r"(\[\[|\]\]|\{\{|\}\}|__|[A-Za-z]+_[A-Za-z]+|[A-Za-z]{4,}\]\)|\)\][A-Za-z]{2,})")
    for text in texts:
        stripped = text.strip()
        if not stripped:
            continue
        if '\\"' in stripped or '".' in stripped or '."' in stripped:
            return "The memo contains garbled quoted fragments rather than clean investor prose."
        if severe_garble.search(stripped):
            return "The memo contains garbled fragments rather than clean investor prose."
        for raw_word in stripped.replace(",", " ").replace(";", " ").split():
            cleaned = raw_word.strip("?.!()[]{}:;\"'")
            if raw_word.count("-") >= 2 and len(cleaned) > 18:
                return "The memo contains garbled compound phrasing rather than clean investor prose."
    return None


def _displayable_open_questions(open_questions: list[str]) -> list[str]:
    if _open_question_quality_feedback(open_questions):
        return []
    allowed_caps = {"SPY", "QQQ", "DIA", "VT", "IWM", "M2", "CPI", "VIX", "DXY", "Fed", "Federal", "Reserve", "Treasury", "Apple", "Buffett", "Marks", "Druckenmiller"}
    displayable: list[str] = []
    for question in open_questions:
        stripped = question.strip()
        if not stripped.endswith("?"):
            continue
        bad_wording = False
        for raw_word in stripped.replace(",", " ").replace(";", " ").split():
            if "-" in raw_word and not any(ch.isdigit() for ch in raw_word):
                bad_wording = True
                break
            cleaned = raw_word.strip("?.!()[]{}:;\"'")
            if cleaned and cleaned[0].isupper() and cleaned not in allowed_caps and raw_word != stripped.split()[0]:
                bad_wording = True
                break
        if not bad_wording:
            displayable.append(question)
    return displayable


def _displayable_memo_points(
    *,
    persona: GuruPersona,
    items: list[str],
    point_type: str,
) -> list[str]:
    keyword_priority: dict[str, tuple[tuple[str, ...], ...]] = {
        WARREN_BUFFETT: (
            ("moat", "pricing power", "brand", "ecosystem", "cash", "owner", "management", "capital allocation"),
            ("margin of safety", "intrinsic value", "price", "valuation", "discount", "premium", "pe", "multiple"),
        ),
        HOWARD_MARKS: (
            ("cycle", "psychology", "sentiment", "optimism", "euphoria", "fear", "fomo", "pendulum"),
            ("risk premium", "paid enough for the risk", "valuation", "breadth", "second-level", "downside"),
        ),
        STANLEY_DRUCKENMILLER: (
            ("liquidity", "rates", "yield", "bond", "earnings", "tape", "momentum", "animal spirits"),
            ("breadth", "volatility", "macro", "risk-reward", "valuation", "tradeoff", "edge"),
        ),
    }
    tiers = keyword_priority.get(persona.name, ((),))
    scored: list[tuple[int, str]] = []
    fallback: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped:
            continue
        if _narrative_quality_feedback([stripped]):
            continue
        if any(marker in stripped for marker in ("[[", "]]", "{{", "}}", "__", "....", "=>")):
            continue
        normalized = _normalize_text(stripped)
        words = normalized.split()
        if len(words) < 4:
            continue
        score = 0
        for index, tier in enumerate(tiers):
            if any(term in normalized for term in tier):
                score = max(score, len(tiers) - index)
        if point_type == "evidence" and score == 0 and persona.name == STANLEY_DRUCKENMILLER:
            if any(term in normalized for term in ("spy", "qqq", "s&p", "nasdaq")):
                score = 1
        if score > 0:
            scored.append((score, stripped))
        else:
            fallback.append(stripped)
    scored.sort(key=lambda item: (-item[0], items.index(item[1])))
    selected = [item for _, item in scored[:3]]
    if not selected:
        selected = fallback[:3]
    return selected


def _persona_render_lines(*, persona: GuruPersona, memo: GuruResearchMemo) -> list[str]:
    display_questions = _displayable_open_questions(memo.open_questions)
    if persona.name == WARREN_BUFFETT:
        evidence = [
            item
            for item in memo.key_evidence
            if not _contains_any(_normalize_text(item), ("rsi", "macd", "bollinger", "overbought", "upper band"))
        ]
        if not evidence:
            evidence = memo.key_evidence
        evidence = _displayable_memo_points(persona=persona, items=evidence, point_type="evidence")
        risks = _displayable_memo_points(persona=persona, items=memo.risks, point_type="risks")
        lines = [
            f"From a {persona.display_name} lens, I would not make too much of day-to-day market swings.",
            "Mr. Market may be cheerful here, but that is not the same as offering a generous price.",
            memo.thesis.strip(),
        ]
        if evidence:
            lines.append("")
            lines.append("What would matter in that frame:")
            for item in evidence[:3]:
                lines.append(f"- {item}")
        if risks:
            lines.append("")
            lines.append("Why that lens would still stay patient:")
            for item in risks[:2]:
                lines.append(f"- {item}")
        if display_questions:
            lines.append("")
            lines.append("What Buffett would want to know before doing more:")
            for item in display_questions[:2]:
                lines.append(f"- {item}")
        return lines
    if persona.name == HOWARD_MARKS:
        evidence = _displayable_memo_points(persona=persona, items=memo.key_evidence, point_type="evidence")
        risks = _displayable_memo_points(persona=persona, items=memo.risks, point_type="risks")
        lines = [
            f"From a {persona.display_name} lens, the first question is where we are in the cycle and whether investors are mistaking optimism for safety.",
            memo.thesis.strip(),
        ]
        if evidence:
            lines.append("")
            lines.append("What supports that cycle read:")
            for item in evidence[:3]:
                lines.append(f"- {item}")
        if risks:
            lines.append("")
            lines.append("What could make that judgment too neat:")
            for item in risks[:2]:
                lines.append(f"- {item}")
        if display_questions:
            lines.append("")
            lines.append("What Marks would still want to test:")
            for item in display_questions[:2]:
                lines.append(f"- {item}")
        return lines
    if persona.name == STANLEY_DRUCKENMILLER:
        evidence = _displayable_memo_points(persona=persona, items=memo.key_evidence, point_type="evidence")
        risks = _displayable_memo_points(persona=persona, items=memo.risks, point_type="risks")
        lines = [
            f"From a {persona.display_name} lens, the real issue is the macro tradeoff rather than a tidy one-line market call.",
            "When the tape stays decent but rates and liquidity are still a live constraint, the broad index bet usually gets messier than the headline looks.",
            memo.thesis.strip(),
        ]
        if evidence:
            lines.append("")
            lines.append("What is driving that macro read:")
            for item in evidence[:3]:
                lines.append(f"- {item}")
        if risks:
            lines.append("")
            lines.append("What could flip the setup:")
            for item in risks[:2]:
                lines.append(f"- {item}")
        if display_questions:
            lines.append("")
            lines.append("What Druckenmiller would want to clarify next:")
            for item in display_questions[:2]:
                lines.append(f"- {item}")
        return lines

    stance_text = {
        "bullish": "leans constructive",
        "bearish": "leans cautious",
        "neutral": "leans cautious neutrality",
        "abstain": "would avoid forcing a conclusion",
    }[memo.stance]
    lines = [f"From a {persona.display_name} lens, the current read {stance_text}.", memo.thesis.strip()]
    if memo.key_evidence:
        lines.append("")
        lines.append("What drives that view:")
        for item in memo.key_evidence[:3]:
            lines.append(f"- {item}")
    return lines


def _should_direct_render_multi_guru(*, user_message: str, route_plan: GuruRoutePlan) -> bool:
    normalized_request = _normalize_text(user_message)
    return route_plan.route_type == "explicit" and len(route_plan.selected_gurus) > 1 and (
        _contains_any(normalized_request, _COMPARISON_TERMS) or len(route_plan.selected_gurus) >= 3
    )


def _render_multi_guru_comparison_reply(
    *,
    memos: list[GuruResearchMemo],
    route_plan: GuruRoutePlan,
    persona_registry: PersonaRegistry,
    failures: list[dict[str, str]],
) -> TerraFinConversationMessage:
    memo_by_guru = {memo.guru: memo for memo in memos}
    ordered = [memo_by_guru[guru] for guru in route_plan.selected_gurus if guru in memo_by_guru]
    lines = ["Here is how the investor lenses separate on this setup:"]
    for memo in ordered:
        persona = persona_registry.get(memo.guru)
        display_questions = _displayable_open_questions(memo.open_questions)
        lines.append("")
        lines.append(f"{persona.display_name}:")
        lines.append(f"- Core read: {memo.thesis}")
        if memo.key_evidence:
            lines.append(f"- What this lens leans on: {memo.key_evidence[0]}")
        if memo.risks:
            lines.append(f"- What keeps this lens careful: {memo.risks[0]}")
        if display_questions:
            lines.append(f"- What this lens would still test: {display_questions[0]}")
    if failures:
        lines.append("")
        lines.append("Incomplete lenses:")
        for failure in failures:
            persona = persona_registry.get(failure["guru"])
            lines.append(f"- {persona.display_name}: research path did not complete cleanly.")
    return TerraFinConversationMessage(
        role="assistant",
        content="\n".join(lines),
        metadata={
            "guruRouterApplied": True,
            "guruRouteType": route_plan.route_type,
            "selectedGurus": list(route_plan.selected_gurus),
            "memoSummary": [
                {"guru": memo.guru, "stance": memo.stance, "confidence": memo.confidence} for memo in ordered
            ],
            "guruDirectRender": True,
            "guruComparisonRender": True,
            "failedGurus": list(failures),
        },
    )


__all__ = [
    "GuruOrchestratedReply",
    "GuruResearchMemo",
    "GuruRoutePlan",
    "_select_guru_worker_tools",
    "build_guru_route_plan",
    "maybe_run_guru_orchestrator",
]
