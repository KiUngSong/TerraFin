"""Hidden persona-subagent worker loop and tool-selection helpers.

`_execute_guru_worker` drives one persona session: it lets the model call
TerraFin tools, validates the eventual `submit_guru_research_memo` payload,
asks for one retry on persona-fit failure, and returns a validated
`GuruResearchMemo` (or a failure reason) to the orchestrator.
"""

import json
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import ValidationError

from ..contracts.conversation import (
    TerraFinConversationMessage,
    make_text_block,
    make_tool_result_block,
)
from ..contracts.conversation_state import record_tool_call_history
from ..runtime.recovery import RecoveryTracker
from ..tools import TerraFinToolDefinition
from .feedback import _is_broad_market_request, _normalize_text, _persona_fit_feedback
from .memo import (
    GuruResearchMemo,
    GuruRoutePlan,
    HOWARD_MARKS,
    STANLEY_DRUCKENMILLER,
    WARREN_BUFFETT,
    _GURU_MEMO_TOOL_NAME,
    _build_guru_memo_tool,
    _validate_guru_memo_arguments,
)
from .personas import GuruPersona, PersonaRegistry


if TYPE_CHECKING:
    from ..contracts.conversation import TerraFinHostedConversation
    from ..runtime.loop import TerraFinHostedAgentLoop


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
    # `src/TerraFin/agent/guru/personas/`. The runtime tool adapter already
    # filters by `allowed_capabilities`, so this function intentionally does
    # not impose a second hidden allowlist for the broad-market path --
    # broad-market and ticker-specific guru sessions get the same toolset. To
    # gain or lose access to a capability, edit the persona's YAML.
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
            "indicators": payload.get("indicators"),
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
