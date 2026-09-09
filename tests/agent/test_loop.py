import json

import pytest
from fakes import BaseFakeService as _FakeService
from fakes import fake_chart_opener as _fake_chart_opener

from TerraFin.agent.conversation import is_internal_only_message
from TerraFin.agent.definitions import (
    DEFAULT_HOSTED_AGENT_NAME,
    build_default_agent_definition_registry,
)
from TerraFin.agent.guru import (
    GuruResearchMemo,
    GuruRoutePlan,
    _build_guru_memo_tool,
    _build_guru_research_prompt,
    _persona_fit_feedback,
    _select_guru_worker_tools,
    run_guru_consult,
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


def _public_roles(messages):
    return [message.role for message in messages if not is_internal_only_message(message)]


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
                assistant_message=TerraFinConversationMessage(
                    role="assistant", content="I'll pull the latest snapshot."
                ),
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
                assistant_message=TerraFinConversationMessage(
                    role="assistant", content="I'll pull the latest snapshot."
                ),
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


class _FatalToolErrorService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        # Unclassifiable on purpose: `_classify_tool_error` matches no branch
        # for TypeError, which is the path that re-raises out of the loop.
        raise TypeError("Cannot pass DataFrame to 'pandas.array'")


class _TwoCallBatchModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(call_id="fatal", tool_name="market_snapshot", arguments={"name": "Crude Oil"}),
                TerraFinToolCall(call_id="never-reached", tool_name="market_snapshot", arguments={"name": "SPY"}),
            ),
            stop_reason="tool_calls",
        )


class _OneGoodThenFatalService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        if name == "Crude Oil":
            raise TypeError("Cannot pass DataFrame to 'pandas.array'")
        return super().market_snapshot(name, depth=depth, view=view)


class _GoodThenFatalBatchModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(call_id="good", tool_name="market_snapshot", arguments={"name": "SPY"}),
                TerraFinToolCall(call_id="fatal", tool_name="market_snapshot", arguments={"name": "Crude Oil"}),
            ),
            stop_reason="tool_calls",
        )


class _RepeatedCallIdModel:
    """A provider that mints positional call ids, so step 2 reuses step 1's."""

    def complete(self, *, messages, tools, **kwargs):
        _ = tools, kwargs
        answered_once = any(message.role == "tool" for message in messages)
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(
                    call_id="positional-call:0",
                    tool_name="market_snapshot",
                    arguments={"name": "Crude Oil" if answered_once else "SPY"},
                ),
            ),
            stop_reason="tool_calls",
        )


class _TransientOnRetryService(_FakeService):
    """First attempt looks like a bad name; the repaired retry hits an outage."""

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        from TerraFin.data.providers.market.yfinance import TransientMarketDataError

        if name == "Crude Oil":
            raise LookupError("No data found for 'Crude Oil'")
        if name == "CRUDE OIL":
            raise TransientMarketDataError("upstream rate limited")
        return super().market_snapshot(name, depth=depth, view=view)


class _CrudeOilModel:
    def complete(self, *, messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return TerraFinModelTurn(
            tool_calls=(
                TerraFinToolCall(call_id="oil", tool_name="market_snapshot", arguments={"name": "Crude Oil"}),
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
                            "citations": [
                                "DCF context highlights current assumptions rather than clear distress pricing."
                            ],
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
                            "key_evidence": [
                                "Investor psychology looks more eager than fearful.",
                                "Risk premiums do not look especially generous.",
                            ],
                            "risks": ["Markets can stay richer for longer than caution feels comfortable."],
                            "open_questions": [
                                "What would cause compensation for risk to widen materially from here?"
                            ],
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


def test_loop_guard_short_circuits_identical_tool_calls() -> None:
    """Duplicate-call detection: after 2 identical (tool_name, args) invocations
    in a single run, the 3rd+ call is short-circuited with a loop_guard error
    instead of executing the real tool again. Verified via the service-level
    call counter: the backing handler runs at most twice."""
    call_count = {"market_snapshot": 0}

    class _CountingService(_FakeService):
        def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
            call_count["market_snapshot"] += 1
            return super().market_snapshot(name, depth=depth, view=view)

    loop = _loop(_LoopingModel(), max_steps=6, service=_CountingService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:guarded")

    # LoopingModel always returns the same (tool_name, args). Without the guard
    # this would execute market_snapshot 6 times (once per step).
    with pytest.raises(RuntimeError, match="exceeded max_steps=6"):
        loop.submit_user_message(conversation.session_id, "loop on me")

    # Guard fires on the 3rd call → only the first 2 actually execute.
    assert call_count["market_snapshot"] == 2, f"expected 2 real executions, got {call_count['market_snapshot']}"


def test_a_raising_tool_still_leaves_every_tool_call_answered() -> None:
    """The tool_use message is persisted for the whole batch before any call
    runs, so a raise must not leave a call without its result: the client reads
    an unanswered call as an interrupted turn and refuses the next message."""
    loop = _loop(_TwoCallBatchModel(), service=_FatalToolErrorService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:fatal-batch")

    with pytest.raises(TypeError, match="Cannot pass DataFrame"):
        loop.submit_user_message(conversation.session_id, "how is crude oil doing")

    messages = loop.get_conversation(conversation.session_id).snapshot()
    results = {message.tool_call_id: message for message in messages if message.role == "tool"}
    # "never-reached" too: the raise aborts the batch before it executes.
    assert set(results) == {"fatal", "never-reached"}
    assert all(message.metadata["errorCode"] == "tool_call_unresolved" for message in results.values())
    # The call that never ran must not be reported as having failed itself —
    # the model reads these results on the next turn.
    assert "Cannot pass DataFrame" in json.loads(results["fatal"].content)["payload"]["error"]["message"]
    assert json.loads(results["never-reached"].content)["payload"]["error"]["message"].startswith("Never executed:")


def test_an_already_answered_call_is_not_answered_twice_when_a_later_call_raises() -> None:
    """Two results for one call reach the model as contradictory answers, so
    the abort path must read what the conversation already holds rather than
    trust a set kept alongside it."""
    loop = _loop(_GoodThenFatalBatchModel(), service=_OneGoodThenFatalService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:no-double-answer")

    with pytest.raises(TypeError, match="Cannot pass DataFrame"):
        loop.submit_user_message(conversation.session_id, "compare SPY and crude oil")

    messages = loop.get_conversation(conversation.session_id).snapshot()
    answered = [message.tool_call_id for message in messages if message.role == "tool"]
    assert answered == ["good", "fatal"], f"expected one result per call, got {answered}"
    good = next(message for message in messages if message.tool_call_id == "good")
    assert good.metadata["isError"] is False


def test_a_call_id_reused_from_an_earlier_step_still_gets_its_own_result() -> None:
    """Call ids are not unique across steps for every provider, so an earlier
    step's answer must not make this step's call look answered."""
    loop = _loop(_RepeatedCallIdModel(), max_steps=4, service=_OneGoodThenFatalService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:reused-call-id")

    with pytest.raises(TypeError, match="Cannot pass DataFrame"):
        loop.submit_user_message(conversation.session_id, "SPY first, then crude oil")

    messages = loop.get_conversation(conversation.session_id).snapshot()
    results = [message for message in messages if message.role == "tool"]
    # One per requested call, even though both carry the same id.
    assert [message.tool_call_id for message in results] == ["positional-call:0"] * 2
    assert [message.metadata["errorCode"] for message in results] == [None, "tool_call_unresolved"]


def test_an_outage_on_the_repaired_retry_is_not_reported_as_a_bad_symbol() -> None:
    """The retry's own error outranks the first attempt's when it must surface:
    an upstream outage reported as an unresolvable name sends the model back to
    the same dead provider."""
    from TerraFin.data.providers.market.yfinance import TransientMarketDataError

    loop = _loop(_CrudeOilModel(), max_steps=2, service=_TransientOnRetryService())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="loop:transient-on-retry")

    with pytest.raises(TransientMarketDataError, match="rate limited"):
        loop.submit_user_message(conversation.session_id, "how is crude oil")

    # The turn still owes the call a result — the invariant holds on this path too.
    messages = loop.get_conversation(conversation.session_id).snapshot()
    results = [message for message in messages if message.role == "tool"]
    assert [message.tool_call_id for message in results] == ["oil"]
    assert "rate limited" in json.loads(results[0].content)["payload"]["error"]["message"]


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
    assert (
        "Do not treat SPY, QQQ, DIA, or VT like standalone operating businesses with moats and owner earnings."
        in prompt
    )
    assert (
        "use market_snapshot, market_data, risk_profile, valuation, and economic rather than free-form macro_focus guesses."
        in prompt
    )
    assert (
        "Use economic with canonical names such as Federal Funds Effective Rate, Treasury-10Y, M2, or SOMA" in prompt
    )
    assert (
        "Do not call company_info, earnings, financials, or fundamental_screen on SPY, QQQ, DIA, VT, or similar benchmark ETFs."
        in prompt
    )
    assert "Prefer a compact 2-4 tool plan" in prompt
    assert (
        "`submit_guru_research_memo` must include: stance, confidence, thesis, key_evidence, risks, open_questions, citations."
        in prompt
    )
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
            key_evidence=[
                "Psychology looks more eager than fearful.",
                "Risk premiums do not look generous.",
                "This feels closer to second-level caution than a precise forecast.",
            ],
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


def test_select_guru_worker_tools_honors_yaml_allowlists_only() -> None:
    """The legacy broad-market allowlist override in `_select_guru_worker_tools`
    has been removed — persona toolsets are now driven solely by each
    persona's YAML `allowed_capabilities` (single source of truth). This test
    verifies the YAML allowlists are honored uniformly regardless of
    broad_market context. Update each persona's YAML to gain or lose access.
    """
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

    # Each persona's YAML drives their toolset; verify a few representative
    # capabilities present/absent for each. The full allowlists live in
    # `src/TerraFin/agent/personas/*.yaml`.
    assert "valuation" in buffett_names
    assert "sec_filings" in buffett_names  # added so Buffett can read 10-Ks
    assert "current_view_context" in buffett_names

    assert "valuation" in marks_names
    assert "economic" in marks_names
    assert "fear_greed" in marks_names  # added for cycle/sentiment work
    assert "market_breadth" in marks_names
    assert "current_view_context" in marks_names

    assert "valuation" in druck_names  # macro guy still needs DCF anchor
    assert "risk_profile" in druck_names
    assert "current_view_context" in druck_names


# ---------------------------------------------------------------------------
# Orchestrator-as-tool architecture tests: the main assistant calls persona
# subagents via consult_<persona> tools — no regex pre-route.
# ---------------------------------------------------------------------------


class _SingleMemoGuruModel:
    """Model stub that submits a valid guru memo on its first persona-session
    turn. Orchestrator-side turns (no memo tool present) return a direct
    no-op answer so only the persona subagent path is exercised."""

    def complete(self, *, agent, session, conversation, messages, tools, **kwargs):
        _ = agent, session, conversation, messages, kwargs
        memo_tool = next(
            (tool for tool in tools if tool.name == "submit_guru_research_memo"),
            None,
        )
        if memo_tool is None:
            return TerraFinModelTurn(
                assistant_message=TerraFinConversationMessage(
                    role="assistant",
                    content="Orchestrator noop (test stub).",
                ),
            )
        return TerraFinModelTurn(
            assistant_message=None,
            tool_calls=(
                TerraFinToolCall(
                    call_id=f"memo-{memo_tool.name}",
                    tool_name=memo_tool.name,
                    arguments={
                        "guru": "warren-buffett",
                        "stance": "neutral",
                        "confidence": 70,
                        "thesis": (
                            "This reads like a wonderful business worth owning, "
                            "but price discipline matters — only invest with a real margin of safety."
                        ),
                        "key_evidence": [
                            "Simple business model with pricing power and owner-friendly capital allocation.",
                            "Durable owner earnings justify patience while cash piles up optionality.",
                        ],
                        "risks": [
                            "Capital intensity could erode long-term returns if reinvestment needs grow.",
                        ],
                        "open_questions": [
                            "What price would leave enough margin of safety on a conservative valuation?",
                        ],
                        "citations": [],
                    },
                ),
            ),
            stop_reason="tool_calls",
        )


def test_consult_tools_exposed_only_to_default_assistant_not_to_personas() -> None:
    """Persona subagents must NOT see consult_<persona> tools themselves —
    otherwise Buffett → consult Marks → consult Druckenmiller → consult
    Buffett could recurse. Filtering uses `is_internal_agent_definition`."""
    loop = _loop_with_gurus(_DirectAnswerModel())

    public_tools = {tool.name for tool in loop.tool_adapter.list_tools_for_agent(DEFAULT_HOSTED_AGENT_NAME)}
    assert "consult_warren_buffett" in public_tools
    assert "consult_howard_marks" in public_tools
    assert "consult_stanley_druckenmiller" in public_tools

    buffett_tools = {tool.name for tool in loop.tool_adapter.list_tools_for_agent("warren-buffett")}
    assert "consult_warren_buffett" not in buffett_tools
    assert "consult_howard_marks" not in buffett_tools
    assert "consult_stanley_druckenmiller" not in buffett_tools


def test_consult_tools_carry_contract_descriptions_that_guide_persona_choice() -> None:
    loop = _loop_with_gurus(_DirectAnswerModel())
    tools_by_name = {tool.name: tool for tool in loop.tool_adapter.list_tools_for_agent(DEFAULT_HOSTED_AGENT_NAME)}

    buffett = tools_by_name["consult_warren_buffett"]
    assert "business" in buffett.description.lower() and "moat" in buffett.description.lower()

    marks = tools_by_name["consult_howard_marks"]
    assert "cycle" in marks.description.lower() and "downside" in marks.description.lower()

    druck = tools_by_name["consult_stanley_druckenmiller"]
    assert "macro" in druck.description.lower() and "regime" in druck.description.lower()


def test_consult_guru_method_returns_structured_memo_dict() -> None:
    loop = _loop_with_gurus(_SingleMemoGuruModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:consult-direct",
    )

    result = loop.consult_guru(
        conversation.session_id,
        "warren-buffett",
        "Is this a good business to own long term?",
    )

    assert result["status"] == "ok"
    assert result["guru"] == "warren-buffett"
    assert 0 <= result["confidence"] <= 100
    assert result["thesis"]
    assert isinstance(result["keyEvidence"], list)
    assert isinstance(result["risks"], list)


def test_consult_guru_rejects_unknown_persona_with_status_error() -> None:
    loop = _loop_with_gurus(_SingleMemoGuruModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:consult-unknown",
    )

    result = loop.consult_guru(
        conversation.session_id,
        "unknown-guru",
        "any question",
    )

    assert result["status"] == "error"
    assert "Unknown persona" in result["reason"]


def test_consult_tool_via_tool_adapter_returns_memo_payload() -> None:
    """End-to-end: orchestrator dispatch `consult_*` through adapter →
    loop.consult_guru → hidden persona session → memo dict as
    tool_result payload."""
    loop = _loop_with_gurus(_SingleMemoGuruModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:consult-tool-adapter",
    )

    invocation = loop.tool_adapter.run_tool(
        conversation.session_id,
        "consult_warren_buffett",
        {"question": "What about Apple's moat?"},
    )

    assert invocation.is_error is False
    assert invocation.payload["status"] == "ok"
    assert invocation.payload["guru"] == "warren-buffett"
    assert invocation.payload["thesis"]


def test_consult_tool_rejects_empty_question_argument() -> None:
    loop = _loop_with_gurus(_SingleMemoGuruModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:consult-empty-question",
    )

    # An empty string violates the contract's own `minLength: 1`, so schema
    # validation now rejects it at the tool boundary and hands the model a
    # retryable error instead of raising. The adapter's own guard still covers
    # what the schema cannot see: a whitespace-only question passes minLength.
    result = loop.tool_adapter.run_tool(
        conversation.session_id,
        "consult_warren_buffett",
        {"question": ""},
    )
    assert result.is_error is True
    assert result.error_code == "tool_invalid_arguments"
    assert "question" in result.error_message

    with pytest.raises(ValueError, match="question"):
        loop.tool_adapter.run_tool(
            conversation.session_id,
            "consult_warren_buffett",
            {"question": "   "},
        )


def test_persona_fit_broad_market_check_runs_on_user_message_under_consult_route() -> None:
    """Under `route_type='consult'` (tool-call routes), the persona-fit
    broad-market branch previously relied on `route_plan.matched_terms`
    + `route_plan.reason` — both empty for live consult calls — so the
    technical-hits rejection silently went dead. Fix: `user_message`
    is now passed through to `_persona_fit_feedback`. Verify: a
    broad-market Buffett memo that leans on RSI/MACD with no signature
    concepts still gets rejected under `route_type='consult'`."""
    registry = build_default_persona_registry()
    buffett = registry.get("warren-buffett")

    # Broad-market question (index-level, no ticker scope).
    broad_question = "What should I think about the S&P 500 right now?"

    # Technical-dominant memo with no signature concepts — should reject.
    bad_memo = GuruResearchMemo(
        guru="warren-buffett",
        stance="neutral",
        confidence=55,
        thesis="Readings look mixed on the tape.",
        key_evidence=[
            "RSI has drifted toward overbought on the S&P 500.",
            "MACD shows a fading crossover with upper Bollinger bands stretched.",
        ],
        risks=["Overbought conditions can extend further."],
        open_questions=["What does the VIX term structure imply?"],
        citations=[],
    )
    feedback = _persona_fit_feedback(
        persona=buffett,
        route_plan=GuruRoutePlan(route_type="consult"),
        memo=bad_memo,
        user_message=broad_question,
    )
    # Must return non-None feedback — that's what triggers the in-turn retry.
    assert feedback is not None
    assert "technical" in feedback.lower() or "signature" in feedback.lower() or "buffett" in feedback.lower()


def test_submit_user_message_no_longer_pre_intercepts_with_guru_router() -> None:
    """Regression: the old regex pre-route that hijacked `submit_user_message`
    before the main model saw the request is gone. An analytical prompt
    like 'how would Howard Marks see this' must flow into the orchestrator
    model loop as a normal turn."""
    loop = _loop_with_gurus(_DirectAnswerModel())
    conversation = loop.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="loop:no-pre-route",
    )

    result = loop.submit_user_message(
        conversation.session_id,
        "How would Howard Marks see cycle risk right now?",
    )

    # Direct answer from the stub, not a guru-memo render.
    assert result.final_message is not None
    assert result.final_message.content == "No tool call needed for this greeting."
    # No hidden intercept — `selectedGurus` metadata key is not present.
    assert (result.final_message.metadata or {}).get("selectedGurus") is None
