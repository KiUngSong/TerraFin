"""Hidden investor-persona subagents for the main ``TerraFin Agent``.

The user-facing product surface stays as a single ``TerraFin Agent``. That
main assistant acts as the **orchestrator**: it decides, per-turn, whether
to consult one or more hidden investor-persona subagents (Warren Buffett,
Howard Marks, Stanley Druckenmiller) by calling a ``consult_<persona>``
tool. The LLM makes that decision with context in hand — this module no
longer gates behaviour on a regex router; it exposes the memo-generation
machinery the orchestrator drives via tool-calls.

Public entry point: :func:`run_guru_consult`.
"""

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .conversation import TerraFinConversationMessage, make_text_block, make_tool_result_block
from .conversation_state import record_tool_call_history
from .personas import GuruPersona, PersonaRegistry, build_default_persona_registry
from .recovery import RecoveryTracker
from .tools import TerraFinToolDefinition


if TYPE_CHECKING:
    from .conversation import TerraFinHostedConversation
    from .loop import TerraFinHostedAgentLoop


GuruStance = Literal["bullish", "bearish", "neutral", "abstain"]
# `consult` is the only route type today. It marks a hidden persona subagent
# session that was spawned by a `consult_<persona>` tool-call from the main
# orchestrator agent (see `docs/agent/architecture.md#orchestrator--persona-subagents`).
# Legacy literal values stay in the type for transcript-log replay of sessions
# created before the orchestrator-as-tool refactor.
GuruRouteType = Literal["consult", "explicit", "portfolio", "macro", "valuation"]

WARREN_BUFFETT = "warren-buffett"
HOWARD_MARKS = "howard-marks"
STANLEY_DRUCKENMILLER = "stanley-druckenmiller"


@dataclass(frozen=True, slots=True)
class GuruRoutePlan:
    """Metadata threaded into a persona subagent's research prompt.

    Under the orchestrator-as-tool architecture, each `consult_<persona>`
    call produces one plan scoped to one guru (`selected_gurus` is always
    length-1 for new-style plans). The shape is kept for transcript-log
    continuity and to avoid rewriting `_run_guru_research_memo` /
    `_build_guru_research_prompt` — they accept this dataclass.
    """
    route_type: GuruRouteType = "consult"
    selected_gurus: tuple[str, ...] = ()
    reason: str = ""
    matched_terms: tuple[str, ...] = ()
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

    @model_validator(mode="after")
    def _clamp_unsupported_confidence(self) -> "GuruResearchMemo":
        # A persona that claims high conviction without any citations is almost
        # always overstating. Clamp to keep the orchestrator from treating an
        # unsupported guess as a strong signal. The orchestrator surfaces the
        # note appended to `thesis` so the user sees why confidence dropped.
        if self.confidence >= 80 and not self.citations:
            self.confidence = 60
            note = "(confidence reduced: no citations supplied)"
            if note not in self.thesis:
                self.thesis = f"{self.thesis.rstrip()} {note}"
        return self



_GURU_MEMO_TOOL_NAME = "submit_guru_research_memo"
_GURU_MEMO_TOOL_DESCRIPTION = "Submit the final structured guru research memo after you finish tool-based research."


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
            "reason": failure_reason
            or "The consulted persona could not produce a structured memo.",
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
                user_message=request,
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
    # Persona tool allowlists are defined in the YAML files under
    # `src/TerraFin/agent/personas/`. The runtime tool adapter already filters
    # by `allowed_capabilities`, so this function intentionally does not impose
    # a second hidden allowlist for the broad-market path — broad-market and
    # ticker-specific guru sessions get the same toolset. To gain or lose
    # access to a capability, edit the persona's YAML.
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
    user_message: str | None = None,
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
    # Broad-market detection needs the raw question text — legacy routes
    # stashed signal into `route_plan.matched_terms` / `route_plan.reason`,
    # but `consult_<persona>` tool calls leave both empty. Prefer the
    # user_message when supplied; fall back to the route-plan fields for
    # transcript-replay of legacy plans.
    broad_market_text = _normalize_text(
        user_message
        if user_message is not None
        else " ".join(route_plan.matched_terms) + " " + route_plan.reason
    )
    broad_market = _is_broad_market_request(
        broad_market_text,
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



__all__ = [
    "GuruResearchMemo",
    "GuruRoutePlan",
    "WARREN_BUFFETT",
    "HOWARD_MARKS",
    "STANLEY_DRUCKENMILLER",
    "_select_guru_worker_tools",
    "run_guru_consult",
]
