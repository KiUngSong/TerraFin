import json

import pytest

from TerraFin.agent.definitions import (
    DEFAULT_HOSTED_AGENT_NAME,
    build_default_agent_definition_registry,
)
from TerraFin.agent.conversation import is_internal_only_message
from TerraFin.agent.guru import (
    GuruResearchMemo,
    GuruRoutePlan,
    _build_guru_memo_tool,
    _build_guru_research_prompt,
    _persona_fit_feedback,
    _persona_render_lines,
    _select_guru_worker_tools,
    build_guru_route_plan,
)
from TerraFin.agent.hosted_runtime import TerraFinHostedAgentRuntime
from TerraFin.agent.loop import (
    TerraFinConversationMessage,
    TerraFinHostedAgentLoop,
    TerraFinModelTurn,
    TerraFinToolCall,
)
from TerraFin.agent.personas import build_default_persona_registry
from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.session_store import SQLiteHostedSessionStore
from TerraFin.agent.transcript_store import HostedTranscriptStore


def _processing() -> dict[str, object]:
    return {
        "requestedDepth": "auto",
        "resolvedDepth": "full",
        "loadedStart": "2024-01-01",
        "loadedEnd": "2024-12-31",
        "isComplete": True,
        "hasOlder": False,
        "sourceVersion": "test-source",
        "view": "daily",
    }


def _public_roles(messages):
    return [message.role for message in messages if not is_internal_only_message(message)]


class _FakeService:
    def resolve(self, query: str) -> dict[str, object]:
        return {"type": "stock", "name": query.upper(), "path": f"/stock/{query.upper()}", "processing": _processing()}

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"ticker": name, "seriesType": "candlestick", "count": 1, "data": [], "processing": {**_processing(), "requestedDepth": depth, "view": view}}

    def indicators(
        self,
        name: str,
        indicators: str,
        *,
        depth: str = "auto",
        view: str = "daily",
    ) -> dict[str, object]:
        return {
            "ticker": name,
            "indicators": {"rsi": {"name": "rsi", "offset": 0, "values": {"value": 55.0}}},
            "unknown": [],
            "processing": {**_processing(), "requestedDepth": depth, "view": view, "indicatorQuery": indicators},
        }

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "ticker": name,
            "price_action": {"current": 100.0},
            "indicators": {"rsi": 55.0},
            "market_breadth": [],
            "watchlist": [],
            "processing": {**_processing(), "requestedDepth": depth, "view": view},
        }

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {"name": name, "confidence": 0.2, "processing": {**_processing(), "requestedDepth": depth, "view": view}}

    def company_info(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "shortName": f"{ticker} Corp", "processing": _processing()}

    def earnings(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker, "earnings": [], "processing": _processing()}

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, object]:
        return {"ticker": ticker, "statement": statement, "period": period, "columns": [], "rows": [], "processing": _processing()}

    def portfolio(self, guru: str) -> dict[str, object]:
        return {"guru": guru, "info": {}, "holdings": [], "count": 0, "processing": _processing()}

    def economic(self, indicators: str) -> dict[str, object]:
        return {"indicators": {indicators: {"latest_value": 3.0}}, "processing": _processing()}

    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        return {
            "name": name,
            "info": {"name": name, "type": "index", "description": "Macro", "currentValue": 1.0, "change": 0.0, "changePercent": 0.0},
            "seriesType": "line",
            "count": 1,
            "data": [],
            "processing": {**_processing(), "requestedDepth": depth, "view": view},
        }

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return {"events": [], "count": 0, "month": month, "year": year, "categories": categories, "limit": limit, "processing": _processing()}

    def fundamental_screen(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "moat": {"score": "wide"},
            "earnings_quality": {},
            "balance_sheet": {},
            "capital_allocation": {},
            "pricing_power": {},
            "warnings": [],
            "processing": _processing(),
        }

    def risk_profile(self, name: str, *, depth: str = "auto") -> dict[str, object]:
        return {
            "ticker": name,
            "tail_risk": {},
            "convexity": {},
            "volatility": {"requestedDepth": depth},
            "drawdown": {},
            "warnings": [],
            "processing": _processing(),
        }

    def valuation(self, ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "dcf": {"status": "ready", "intrinsic_value": 120.0},
            "reverse_dcf": {"status": "ready", "implied_growth_pct": 8.0},
            "relative": {"trailing_pe": 22.0},
            "graham_number": 100.0,
            "margin_of_safety_pct": 12.0,
            "current_price": 107.0,
            "processing": _processing(),
        }


def _fake_chart_opener(
    data_or_names,
    *,
    session_id: str | None = None,
    **kwargs,
) -> dict[str, object]:
    _ = kwargs
    return {
        "ok": True,
        "sessionId": session_id or "agent:chart",
        "chartUrl": f"http://127.0.0.1:8001/chart?sessionId={session_id or 'agent:chart'}",
        "processing": _processing(),
        "inputEcho": data_or_names,
    }


def _loop(model_client, *, max_steps: int = 8, service: _FakeService | None = None) -> TerraFinHostedAgentLoop:
    service = service or _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    runtime = TerraFinHostedAgentRuntime(service=service, capability_registry=registry)
    return TerraFinHostedAgentLoop(runtime=runtime, model_client=model_client, max_steps=max_steps)


def _sqlite_loop(model_client, *, db_path, max_steps: int = 8) -> TerraFinHostedAgentLoop:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(
            db_path=db_path,
            service=service,
            registry=registry,
        ),
        transcript_store=HostedTranscriptStore(root_dir=db_path.parent / "transcripts"),
    )
    return TerraFinHostedAgentLoop(runtime=runtime, model_client=model_client, max_steps=max_steps)


def _loop_with_gurus(model_client, *, max_steps: int = 8) -> TerraFinHostedAgentLoop:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        agent_registry=build_default_agent_definition_registry(include_gurus=True),
    )
    return TerraFinHostedAgentLoop(runtime=runtime, model_client=model_client, max_steps=max_steps)


class _SnapshotThenSummarizeModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = kwargs
        assert tools
        last_tool = next((message for message in reversed(messages) if message.role == "tool"), None)
        if last_tool is None:
            return TerraFinModelTurn(
                assistant_message=TerraFinConversationMessage(role="assistant", content="I'll pull the latest snapshot."),
                tool_calls=(
                    TerraFinToolCall(
                        call_id="call-1",
                        tool_name="market_snapshot",
                        arguments={"name": "AAPL"},
                    ),
                ),
                stop_reason="tool_calls",
            )
        payload = json.loads(last_tool.content)
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content=f"{payload['payload']['ticker']} snapshot retrieved.",
            ),
            stop_reason="completed",
        )


class _DirectAnswerModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="No tool call needed for this greeting.",
            )
        )


class _LoopingModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(role="assistant", content="Still working."),
            tool_calls=(TerraFinToolCall(call_id="loop", tool_name="market_snapshot", arguments={"name": "MSFT"}),),
            stop_reason="tool_calls",
        )


class _PromptBudgetRetryModel:
    def __init__(self) -> None:
        self.observed: list[dict[str, int | bool]] = []

    def complete(self, *, messages, tools, **kwargs):
        _ = tools, kwargs
        max_tool_length = max((len(message.content) for message in messages if message.role == "tool"), default=0)
        max_text_length = max(
            (len(message.content) for message in messages if message.role in {"user", "assistant"}),
            default=0,
        )
        saw_compaction_notice = any(
            message.role == "system" and "Earlier conversation context was compacted" in message.content
            for message in messages
        )
        snapshot = {
            "message_count": len(messages),
            "max_tool_length": max_tool_length,
            "max_text_length": max_text_length,
            "saw_compaction_notice": saw_compaction_notice,
        }
        self.observed.append(snapshot)

        if len(messages) > 16 or max_tool_length > 500 or max_text_length > 2000:
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': 'prompt token count of 163398 exceeds the limit of 64000', "
                "'code': 'model_max_prompt_tokens_exceeded'}}"
            )

        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="Compacted context worked.",
            )
        )


class _AlwaysPromptBudgetFailModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        raise RuntimeError(
            "Error code: 400 - {'error': {'message': 'prompt token count of 163398 exceeds the limit of 64000', "
            "'code': 'model_max_prompt_tokens_exceeded'}}"
        )


class _CacheClobberingSnapshotThenSummarizeModel:
    def __init__(self, runtime: TerraFinHostedAgentRuntime) -> None:
        self.runtime = runtime

    def complete(self, *, messages, tools, **kwargs):
        _ = kwargs
        assert tools
        self.runtime.list_sessions()
        last_tool = next((message for message in reversed(messages) if message.role == "tool"), None)
        if last_tool is None:
            return TerraFinModelTurn(
                assistant_message=TerraFinConversationMessage(role="assistant", content="I'll pull the latest snapshot."),
                tool_calls=(
                    TerraFinToolCall(
                        call_id="call-1",
                        tool_name="market_snapshot",
                        arguments={"name": "AAPL"},
                    ),
                ),
                stop_reason="tool_calls",
            )
        payload = json.loads(last_tool.content)
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content=f"{payload['payload']['ticker']} snapshot retrieved.",
            ),
            stop_reason="completed",
        )


class _UnrepairableToolErrorService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        raise ValueError(f"Invalid ticker: {name}")


class _CurrentMarketStateFailureService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        if name == "CURRENT MARKET STATE":
            raise ValueError(f"Invalid ticker: {name}")
        return super().market_snapshot(name, depth=depth, view=view)


class _ToolErrorRecoveryModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, messages, tools, **kwargs):
        _ = kwargs
        self.calls += 1
        last_tool = next((message for message in reversed(messages) if message.role == "tool"), None)
        if last_tool is None:
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="bad-call",
                        tool_name="market_snapshot",
                        arguments={"name": "CURRENT MARKET STATE"},
                    ),
                ),
                stop_reason="tool_calls",
            )
        payload = json.loads(last_tool.content)
        if payload["payload"].get("error", {}).get("code") == "tool_input_resolution_error":
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="fixed-call",
                        tool_name="market_snapshot",
                        arguments={"name": "SPY"},
                    ),
                ),
                stop_reason="tool_calls",
            )
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="Recovered after internal tool error handling.",
            ),
            stop_reason="completed",
        )


class _StubbornToolErrorModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(
                    call_id="stubborn",
                    tool_name="market_snapshot",
                    arguments={"name": "CURRENT MARKET STATE"},
                ),
            ),
            stop_reason="tool_calls",
        )


class _GuruRouterModel:
    def complete(self, *, agent, messages, tools, **kwargs):
        _ = kwargs
        last_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        memo_tool_name = next((tool.name for tool in tools if tool.name == "submit_guru_research_memo"), None)
        if agent.name == "warren-buffett":
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="memo-buffett",
                        tool_name=memo_tool_name or "submit_guru_research_memo",
                        arguments={
                            "guru": "warren-buffett",
                            "stance": "bullish",
                            "confidence": 81,
                            "thesis": "The portfolio still reflects a quality-first lens with durable businesses.",
                            "key_evidence": ["Top holdings are concentrated in large durable franchises."],
                            "risks": ["Valuation support matters more than admiration for the businesses."],
                            "open_questions": ["Whether the current prices still preserve margin of safety."],
                            "citations": ["Selected guru context points to concentrated top holdings."],
                        },
                    ),
                ),
                stop_reason="tool_calls",
            )
        if agent.name == "howard-marks":
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="memo-marks",
                        tool_name=memo_tool_name or "submit_guru_research_memo",
                        arguments={
                            "guru": "howard-marks",
                            "stance": "neutral",
                            "confidence": 68,
                            "thesis": "The setup looks reasonable, but the risk premium needs more scrutiny before conviction increases.",
                            "key_evidence": ["Cycle position and downside compensation are not obviously generous."],
                            "risks": ["Consensus may already price in too much optimism."],
                            "open_questions": ["How much downside protection is implied by current valuation inputs?"],
                            "citations": ["DCF context highlights current assumptions rather than clear distress pricing."],
                        },
                    ),
                ),
                stop_reason="tool_calls",
            )
        if agent.name == DEFAULT_HOSTED_AGENT_NAME and not tools and "Internal guru research memos" in last_user:
            return TerraFinModelTurn(
                assistant_message=TerraFinConversationMessage(
                    role="assistant",
                    content=(
                        "From a Buffett lens, the portfolio still reads as a quality-first book. "
                        "The main follow-up is whether current prices still leave enough margin of safety."
                    ),
                )
            )
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="General answer.",
            )
        )


class _MalformedGuruMemoModel:
    def complete(self, *, agent, messages, tools, **kwargs):
        _ = kwargs, messages
        memo_tool_name = next((tool.name for tool in tools if tool.name == "submit_guru_research_memo"), None)
        if agent.name == "howard-marks":
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="memo-bad",
                        tool_name=memo_tool_name or "submit_guru_research_memo",
                        arguments={
                            "stance": "neutral",
                            "confidence": "not-an-int",
                            "thesis": "Invalid payload",
                        },
                    ),
                ),
                stop_reason="tool_calls",
            )
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="General answer.",
            )
        )


class _RetryingMalformedGuruMemoModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, agent, messages, tools, **kwargs):
        _ = kwargs
        memo_tool_name = next((tool.name for tool in tools if tool.name == "submit_guru_research_memo"), None)
        if agent.name != "howard-marks":
            return TerraFinModelTurn(
                assistant_message=TerraFinConversationMessage(
                    role="assistant",
                    content="General answer.",
                )
            )
        last_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        if "malformed" in last_user.lower():
            return TerraFinModelTurn(
                tool_calls=(
                    TerraFinToolCall(
                        call_id="memo-good",
                        tool_name=memo_tool_name or "submit_guru_research_memo",
                        arguments={
                            "stance": "neutral",
                            "confidence": 74,
                            "thesis": "The cycle does not justify aggressive optimism because investors are not being paid much for the risk they are taking.",
                            "key_evidence": ["Investor psychology looks more eager than fearful.", "Risk premiums do not look especially generous."],
                            "risks": ["Markets can stay richer for longer than caution feels comfortable."],
                            "open_questions": ["What would cause compensation for risk to widen materially from here?"],
                            "citations": ["SPY snapshot", "QQQ snapshot"],
                        },
                    ),
                ),
                stop_reason="tool_calls",
            )
        self.calls += 1
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(
                    call_id="memo-bad",
                    tool_name=memo_tool_name or "submit_guru_research_memo",
                    arguments={"citations": ["SPY snapshot"]},
                ),
            ),
            stop_reason="tool_calls",
        )


def test_create_session_seeds_system_prompt() -> None:
    loop = _loop(_DirectAnswerModel())

    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:system")

    assert conversation.session_id == "loop:system"
    assert conversation.messages[0].role == "system"
    assert DEFAULT_HOSTED_AGENT_NAME in conversation.messages[0].content


def test_submit_user_message_can_run_tool_then_finalize() -> None:
    loop = _loop(_SnapshotThenSummarizeModel())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:tool")

    result = loop.submit_user_message(conversation.session_id, "Give me the latest AAPL snapshot.")

    assert result.steps == 2
    assert result.final_message is not None
    assert result.final_message.content == "AAPL snapshot retrieved."
    assert len(result.tool_results) == 1
    assert result.tool_results[0].payload["ticker"] == "AAPL"

    messages = loop.get_conversation(conversation.session_id).snapshot()
    assert _public_roles(messages) == ["system", "user", "assistant", "tool", "assistant"]
    assert any(is_internal_only_message(message) for message in messages)


def test_submit_user_message_can_return_direct_answer_without_tools() -> None:
    loop = _loop(_DirectAnswerModel())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:direct")

    result = loop.submit_user_message(conversation.session_id, "hello")

    assert result.steps == 1
    assert result.final_message is not None
    assert result.final_message.content == "No tool call needed for this greeting."
    assert result.tool_results == ()


def test_submit_user_message_persists_assistant_reply_even_if_session_cache_is_rebuilt(tmp_path) -> None:
    loop = _sqlite_loop(None, db_path=tmp_path / "hosted-loop.sqlite3")
    loop.model_client = _CacheClobberingSnapshotThenSummarizeModel(loop.runtime)
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:sqlite-race")

    result = loop.submit_user_message(conversation.session_id, "Give me the latest AAPL snapshot.")

    assert result.final_message is not None
    assert result.final_message.content == "AAPL snapshot retrieved."

    reloaded = loop.runtime.get_session_record(conversation.session_id)
    assert _public_roles(reloaded.conversation.snapshot()) == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


def test_submit_user_message_raises_when_model_never_finishes() -> None:
    loop = _loop(_LoopingModel(), max_steps=2)
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:max-steps")

    with pytest.raises(RuntimeError, match="exceeded max_steps=2"):
        loop.submit_user_message(conversation.session_id, "keep going")


def test_submit_user_message_keeps_recoverable_tool_errors_inside_the_loop_until_model_recovers() -> None:
    model = _ToolErrorRecoveryModel()
    loop = _loop(model, service=_CurrentMarketStateFailureService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:tool-recovery")

    result = loop.submit_user_message(conversation.session_id, "How does the current market state look?")

    assert result.final_message is not None
    assert result.final_message.content == "Recovered after internal tool error handling."
    assert len(result.tool_results) == 2
    assert result.tool_results[0].is_error is True
    assert result.tool_results[0].retryable is True
    assert result.tool_results[1].is_error is False
    assert _public_roles(loop.get_conversation(conversation.session_id).snapshot()) == [
        "system",
        "user",
        "tool",
        "tool",
        "assistant",
    ]


def test_submit_user_message_returns_clean_fallback_after_repeated_recoverable_tool_errors() -> None:
    loop = _loop(_StubbornToolErrorModel(), max_steps=4, service=_UnrepairableToolErrorService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:tool-recovery-fallback")

    result = loop.submit_user_message(conversation.session_id, "How does the current market state look?")

    assert result.final_message is not None
    assert "specific ticker" in result.final_message.content
    assert result.final_message.metadata["internalToolRecovery"] is True
    assert result.final_message.metadata["recoveryErrorCode"] == "tool_input_resolution_error"
    assert any(tool_result.is_error for tool_result in result.tool_results)


def test_submit_user_message_retries_with_compacted_context_when_provider_hits_prompt_limit() -> None:
    model = _PromptBudgetRetryModel()
    loop = _loop(model)
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:prompt-budget-retry")

    oversized_tool_payload = json.dumps(
        {
            "toolName": "market_snapshot",
            "payload": {
                "ticker": "NASDAQ COMPOSITE",
                "notes": "N" * 4000,
                "series": [
                    {
                        "label": f"segment-{index}",
                        "values": ["X" * 900, "Y" * 900],
                    }
                    for index in range(6)
                ],
            },
        }
    )
    for index in range(20):
        conversation.messages.append(
            TerraFinConversationMessage(role="assistant", content=f"Assistant context {index}: " + ("A" * 3200))
        )
        conversation.messages.append(
            TerraFinConversationMessage(
                role="tool",
                name="market_snapshot",
                tool_call_id=f"tool-{index}",
                content=oversized_tool_payload,
            )
        )

    result = loop.submit_user_message(conversation.session_id, "What matters most right now?")

    assert result.final_message is not None
    assert result.final_message.content == "Compacted context worked."
    assert len(model.observed) >= 1
    assert model.observed[-1]["message_count"] <= model.observed[0]["message_count"]
    assert model.observed[-1]["max_tool_length"] <= model.observed[0]["max_tool_length"]
    assert model.observed[-1]["max_tool_length"] <= 500
    assert model.observed[0]["max_text_length"] > 2000
    assert model.observed[-1]["max_text_length"] <= 2000
    assert any(snapshot["saw_compaction_notice"] is True for snapshot in model.observed)


def test_submit_user_message_raises_friendly_error_when_all_prompt_budget_retries_fail() -> None:
    loop = _loop(_AlwaysPromptBudgetFailModel())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:prompt-budget-fail")

    with pytest.raises(RuntimeError, match="internal compaction") as exc_info:
        loop.submit_user_message(conversation.session_id, "Please summarize everything.")

    assert "prompt token count" not in str(exc_info.value)


def test_create_session_binds_guru_persona_prompt_without_manual_override() -> None:
    loop = _loop_with_gurus(_DirectAnswerModel())

    conversation = loop.create_session(
        "warren-buffett",
        session_id="loop:guru-prompt",
        allow_internal=True,
    )

    assert conversation.messages[0].role == "system"
    assert "Warren Buffett" in conversation.messages[0].content
    assert "circle of competence" in conversation.messages[0].content
    assert "Time Horizon" in conversation.messages[0].content


def test_build_guru_route_plan_prefers_marks_for_dcf_review() -> None:
    loop = _loop_with_gurus(_DirectAnswerModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:route-dcf",
        metadata={"viewContextId": "view:dcf"},
    )
    loop.runtime.upsert_view_context(
        "view:dcf",
        route="/stock/AAPL/dcf",
        page_type="dcf",
        title="AAPL DCF",
        selection={"dcfWorkbench": {"mode": "stock", "label": "AAPL"}},
    )

    plan = build_guru_route_plan(
        loop=loop,
        session_id=conversation.session_id,
        user_message="Tell me which assumptions deserve a second look.",
    )

    assert plan is not None
    assert plan.route_type == "valuation"
    assert plan.selected_gurus == ("howard-marks",)


def test_build_guru_route_plan_keeps_all_explicitly_named_gurus() -> None:
    loop = _loop_with_gurus(_DirectAnswerModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:route-explicit-all-gurus",
    )

    plan = build_guru_route_plan(
        loop=loop,
        session_id=conversation.session_id,
        user_message="How would Buffett, Howard Marks, and Druckenmiller disagree on this setup?",
    )

    assert plan is not None
    assert plan.route_type == "explicit"
    assert plan.selected_gurus == ("warren-buffett", "howard-marks", "stanley-druckenmiller")


def test_submit_user_message_treats_cycle_question_as_broad_market_marks_route() -> None:
    loop = _loop_with_gurus(_RetryingMalformedGuruMemoModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:marks-cycle-broad-market",
    )

    result = loop.submit_user_message(conversation.session_id, "From a Howard Marks lens, where are we in the cycle right now?")

    assert result.final_message is not None
    assert "Howard Marks lens" in result.final_message.content
    assert result.final_message.metadata["selectedGurus"] == ["howard-marks"]


def test_submit_user_message_routes_default_assistant_through_hidden_guru_sessions() -> None:
    loop = _loop_with_gurus(_GuruRouterModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:portfolio-route",
        metadata={"viewContextId": "view:buffett"},
    )
    loop.runtime.upsert_view_context(
        "view:buffett",
        route="/market-insights",
        page_type="market-insights",
        title="Warren Buffett Portfolio View",
        selection={"selectedGuru": "Warren Buffett"},
        entities=[{"kind": "portfolio", "id": "Warren Buffett"}],
    )

    result = loop.submit_user_message(conversation.session_id, "What stands out in this portfolio?")

    assert result.final_message is not None
    assert "Warren Buffett lens" in result.final_message.content
    assert "quality-first lens with durable businesses" in result.final_message.content
    assert result.final_message.metadata["guruRouterApplied"] is True
    assert result.final_message.metadata["guruDirectRender"] is True
    assert result.final_message.metadata["selectedGurus"] == ["warren-buffett"]
    assert [message.role for message in loop.get_conversation(conversation.session_id).snapshot()] == [
        "system",
        "user",
        "assistant",
    ]
    assert tuple(record.session_id for record in loop.runtime.list_sessions()) == (conversation.session_id,)


def test_submit_user_message_falls_back_when_guru_memo_validation_fails() -> None:
    loop = _loop_with_gurus(_MalformedGuruMemoModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:explicit-guru-failure",
    )

    result = loop.submit_user_message(conversation.session_id, "How would Howard Marks assess current market status?")

    assert result.final_message is not None
    assert "Howard Marks lens" in result.final_message.content
    assert "low-confidence partial read" in result.final_message.content
    assert result.final_message.metadata["guruRouterApplied"] is True
    assert result.final_message.metadata["guruRouterFailure"] is True
    assert result.final_message.metadata["guruRouterPartial"] is True
    assert result.final_message.metadata["selectedGurus"] == ["howard-marks"]
    reloaded = loop.get_conversation(conversation.session_id)
    failures = reloaded.metadata.get("guruRouterFailures", [])
    assert failures
    assert failures[-1]["selectedGurus"] == ["howard-marks"]


def test_submit_user_message_retries_once_after_guru_memo_validation_error() -> None:
    model = _RetryingMalformedGuruMemoModel()
    loop = _loop_with_gurus(model)
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:explicit-guru-memo-retry",
    )

    result = loop.submit_user_message(conversation.session_id, "How would Howard Marks assess current market status?")

    assert result.final_message is not None
    assert "Howard Marks lens" in result.final_message.content
    assert result.final_message.metadata["guruRouterApplied"] is True
    assert result.final_message.metadata["selectedGurus"] == ["howard-marks"]
    assert model.calls == 1


def test_buffett_broad_market_prompt_disallows_treating_indices_like_businesses() -> None:
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")
    prompt = _build_guru_research_prompt(
        persona=buffett,
        persona_display_name="Warren Buffett",
        user_message="How would Warren Buffett assess current market status?",
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("warren-buffett",),
            reason="Explicit guru mention.",
            matched_terms=("warren-buffett",),
            view_context=None,
        ),
        view_context=None,
    )

    assert "Broad index ETFs are market containers, not operating businesses." in prompt
    assert "Do not force company-style moat, owner earnings, or DCF logic onto SPY, QQQ, DIA, VT" in prompt
    assert "Do not treat SPY, QQQ, DIA, or VT like standalone operating businesses with moats and owner earnings." in prompt
    assert "use market_snapshot, market_data, risk_profile, valuation, and economic rather than free-form macro_focus guesses." in prompt
    assert "Use economic with canonical names such as Federal Funds Effective Rate, Treasury-10Y, M2, or SOMA" in prompt
    assert "Do not call company_info, earnings, financials, or fundamental_screen on SPY, QQQ, DIA, VT, or similar benchmark ETFs." in prompt
    assert "Prefer a compact 2-4 tool plan" in prompt
    assert "`submit_guru_research_memo` must include: stance, confidence, thesis, key_evidence, risks, open_questions, citations." in prompt
    assert "Do not use `resolve` for broad-market questions." in prompt
    assert "The final thesis must explicitly reflect native concepts from this investor's worldview" in prompt
    assert "Open the thesis with one unmistakable worldview sentence" in prompt
    assert "Keep open_questions plain, concrete, and investor-readable" in prompt
    assert "volatility was 'really nothing'" in prompt


def test_buffett_persona_allows_market_snapshot_for_broad_market_checks() -> None:
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")

    assert "market_snapshot" in buffett.allowed_capabilities


def test_persona_fit_feedback_rejects_generic_buffett_technical_memo() -> None:
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")

    feedback = _persona_fit_feedback(
        persona=buffett,
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("warren-buffett",),
            reason="Current market broad index question.",
            matched_terms=("current market", "spy", "qqq"),
            view_context=None,
        ),
        memo=GuruResearchMemo(
            guru="warren-buffett",
            stance="neutral",
            confidence=65,
            thesis="The market looks overbought because RSI, MACD, and Bollinger Bands are stretched.",
            key_evidence=["SPY RSI is high", "QQQ is near the upper Bollinger Band"],
            risks=[],
            open_questions=[],
            citations=[],
        ),
    )

    assert feedback is not None
    assert "signature concepts" in feedback or "Buffett broad-market answer" in feedback


def test_persona_fit_feedback_rejects_buffett_memo_when_technicals_dominate() -> None:
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")

    feedback = _persona_fit_feedback(
        persona=buffett,
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("warren-buffett",),
            reason="Current market broad index question.",
            matched_terms=("current market", "spy", "qqq"),
            view_context=None,
        ),
        memo=GuruResearchMemo(
            guru="warren-buffett",
            stance="neutral",
            confidence=65,
            thesis="The market looks neutral because RSI is elevated and MACD is still constructive.",
            key_evidence=["SPY RSI is high", "QQQ MACD remains positive."],
            risks=[],
            open_questions=[],
            citations=[],
        ),
    )

    assert feedback is not None
    assert "technical-analysis language" in feedback or "cannot lean on RSI" in feedback


def test_persona_fit_feedback_accepts_marks_cycle_psychology_memo() -> None:
    registry = build_default_persona_registry()
    marks = registry.get("howard-marks")

    feedback = _persona_fit_feedback(
        persona=marks,
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("howard-marks",),
            reason="Current market broad index question.",
            matched_terms=("current market", "spy", "qqq"),
            view_context=None,
        ),
        memo=GuruResearchMemo(
            guru="howard-marks",
            stance="bearish",
            confidence=72,
            thesis="The pendulum looks closer to optimism than fear, and the real issue is whether investors are being paid enough for the risk they are taking.",
            key_evidence=["Psychology looks more eager than fearful.", "Risk premiums do not look generous.", "This feels closer to second-level caution than a precise forecast."],
            risks=[],
            open_questions=[],
            citations=[],
        ),
    )

    assert feedback is None


def test_persona_fit_feedback_accepts_clean_buffett_business_memo() -> None:
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")

    feedback = _persona_fit_feedback(
        persona=buffett,
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("warren-buffett",),
            reason="User explicitly asked for Buffett on AAPL valuation.",
            matched_terms=("warren-buffett", "aapl"),
            view_context=None,
        ),
        memo=GuruResearchMemo(
            guru="warren-buffett",
            stance="neutral",
            confidence=76,
            thesis="Apple is a wonderful business, but the current price leaves no margin of safety for a patient owner.",
            key_evidence=[
                "The business still produces strong cash generation and durable pricing power.",
                "At roughly $266 versus an intrinsic value estimate closer to $167, the price asks me to pay up for a business I already admire.",
                "Operating margins remain strong, but the valuation gives me little room for error if growth cools.",
            ],
            risks=[
                "A rich valuation can turn a fine business into a mediocre investment result.",
                "If pricing power softens, today's price would look even less forgiving.",
            ],
            open_questions=[
                "What would have to happen to justify paying today's price without a margin of safety?",
                "How durable is Apple's pricing power if gross margins keep drifting lower?",
            ],
            citations=["functions.company_info", "functions.valuation", "functions.fundamental_screen"],
        ),
    )

    assert feedback is None


def test_persona_fit_feedback_rejects_marks_fragment_open_questions() -> None:
    registry = build_default_persona_registry()
    marks = registry.get("howard-marks")

    feedback = _persona_fit_feedback(
        persona=marks,
        route_plan=GuruRoutePlan(
            route_type="explicit",
            selected_gurus=("howard-marks",),
            reason="Current market broad index question.",
            matched_terms=("current market", "spy", "qqq"),
            view_context=None,
        ),
        memo=GuruResearchMemo(
            guru="howard-marks",
            stance="neutral",
            confidence=68,
            thesis="The pendulum looks closer to optimism than fear, and the key question is whether investors are being paid enough for the risk they are taking.",
            key_evidence=["Cycle position looks late enough that psychology matters more than a neat forecast."],
            risks=[],
            open_questions=["How does ]] current-cycle skew work now?"],
            citations=[],
        ),
    )

    assert feedback is not None
    assert "open questions" in feedback.lower()


def test_select_guru_worker_tools_uses_distinct_broad_market_allowlists() -> None:
    registry = build_default_persona_registry()
    loop = _loop_with_gurus(_DirectAnswerModel())
    buffett_session = loop.create_session("warren-buffett", session_id="loop:buffett-tools", allow_internal=True)
    marks_session = loop.create_session("howard-marks", session_id="loop:marks-tools", allow_internal=True)
    druck_session = loop.create_session("stanley-druckenmiller", session_id="loop:druck-tools", allow_internal=True)
    memo_tool = _build_guru_memo_tool()

    buffett_tools = _select_guru_worker_tools(
        loop=loop,
        session_id=buffett_session.session_id,
        persona=registry.get("warren-buffett"),
        broad_market=True,
        memo_tool=memo_tool,
    )
    marks_tools = _select_guru_worker_tools(
        loop=loop,
        session_id=marks_session.session_id,
        persona=registry.get("howard-marks"),
        broad_market=True,
        memo_tool=memo_tool,
    )
    druck_tools = _select_guru_worker_tools(
        loop=loop,
        session_id=druck_session.session_id,
        persona=registry.get("stanley-druckenmiller"),
        broad_market=True,
        memo_tool=memo_tool,
    )

    buffett_names = {tool.capability_name for tool in buffett_tools}
    marks_names = {tool.capability_name for tool in marks_tools}
    druck_names = {tool.capability_name for tool in druck_tools}

    assert "risk_profile" not in buffett_names
    assert "economic" not in buffett_names
    assert "risk_profile" not in marks_names
    assert "economic" in marks_names
    assert "macro_focus" not in marks_names
    assert "risk_profile" in druck_names
    assert "market_data" not in druck_names
    assert "valuation" not in druck_names
    assert "macro_focus" not in druck_names


def test_persona_render_lines_filters_garbled_druckenmiller_points() -> None:
    registry = build_default_persona_registry()
    druck = registry.get("stanley-druckenmiller")

    lines = _persona_render_lines(
        persona=druck,
        memo=GuruResearchMemo(
            guru="stanley-druckenmiller",
            stance="neutral",
            confidence=65,
            thesis="The macro tradeoff is that animal spirits are back, but higher yields can still lean on multiples if earnings do not outrun them.",
            key_evidence=[
                "SPY up 3.54% and QQQ up 5.17% over the past week, which tells me the tape still has momentum.",
                "Decliner trend often characterized (broad sensitivity) hypo-wide",
                "Treasury yields can still compress equity multiples if liquidity does not improve.",
            ],
            risks=[
                "rates .... adjusted format",
                "If yields keep rising while breadth stays narrow, the index-level edge fades fast.",
            ],
            open_questions=["How will Treasury yield trends affect equity multiples if growth stabilizes?"],
            citations=[],
        ),
    )

    rendered = "\n".join(lines)
    assert "hypo-wide" not in rendered
    assert "rates .... adjusted format" not in rendered
    assert "Treasury yields can still compress equity multiples" in rendered
