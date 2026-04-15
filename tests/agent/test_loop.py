import json

import pytest

from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME
from TerraFin.agent.hosted_runtime import TerraFinHostedAgentRuntime
from TerraFin.agent.loop import (
    TerraFinConversationMessage,
    TerraFinHostedAgentLoop,
    TerraFinModelTurn,
    TerraFinToolCall,
)
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


def _loop(model_client, *, max_steps: int = 8) -> TerraFinHostedAgentLoop:
    service = _FakeService()
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
    assert [message.role for message in messages] == ["system", "user", "assistant", "tool", "assistant"]


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
    assert [message.role for message in reloaded.conversation.snapshot()] == [
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
