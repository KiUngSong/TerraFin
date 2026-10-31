import json

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from TerraFin.agent.contracts.conversation import make_text_block, make_tool_result_block, make_tool_use_block
from TerraFin.agent.definitions import TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation
from TerraFin.agent.model_management import set_saved_provider_credentials
from TerraFin.agent.models.providers.anthropic import (
    ANTHROPIC_CONTENT_KEY,
    REFUSAL_FALLBACK_BETA,
    THINKING_BINDING_BETA,
    TerraFinAnthropicMessagesProvider,
    TerraFinAnthropicModelConfig,
    TerraFinAnthropicModelConfigError,
    TerraFinAnthropicModelResponseError,
)
from TerraFin.agent.runtime import TerraFinAgentSession
from TerraFin.agent.runtime.context_budget import ContextBudgetManager, is_prompt_budget_error
from TerraFin.agent.runtime.transcript_normalizer import TranscriptNormalizer
from TerraFin.agent.tools import TerraFinToolDefinition


def _message(content: list[dict], stop_reason: str = "end_turn", **extra) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            **extra,
        }
    )


class _FakeStream:
    def __init__(self, message: BetaMessage) -> None:
        self._message = message

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get_final_message(self) -> BetaMessage:
        return self._message


class _FakeMessages:
    def __init__(self, responses: list[BetaMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def stream(self, **kwargs) -> _FakeStream:
        self.calls.append(kwargs)
        return _FakeStream(self._responses.pop(0))


class _FakeBeta:
    def __init__(self, responses: list[BetaMessage]) -> None:
        self.messages = _FakeMessages(responses)


class _FakeClient:
    def __init__(self, responses: list[BetaMessage]) -> None:
        self.beta = _FakeBeta(responses)


def _agent() -> TerraFinAgentDefinition:
    return TerraFinAgentDefinition(
        name="market-researcher",
        description="General market agent.",
        allowed_capabilities=("market_snapshot",),
    )


def _tool() -> TerraFinToolDefinition:
    return TerraFinToolDefinition(
        name="market_snapshot",
        capability_name="market_snapshot",
        description="Fetch snapshot.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        execution_mode="invoke",
    )


def _provider(responses: list[BetaMessage], **config) -> tuple[TerraFinAnthropicMessagesProvider, _FakeClient]:
    client = _FakeClient(responses)
    provider = TerraFinAnthropicMessagesProvider(
        config=TerraFinAnthropicModelConfig(api_key="test-key", **config),
        client=client,
    )
    return provider, client


def _complete(provider: TerraFinAnthropicMessagesProvider, messages, model_id: str = "claude-opus-5-5"):
    conversation = TerraFinHostedConversation(
        session_id="anthropic:test", agent_name="market-researcher", messages=list(messages)
    )
    return provider.complete(
        model=provider.resolve_model(model_id),
        agent=_agent(),
        session=TerraFinAgentSession(session_id="anthropic:test"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )


def _tool_message(call_id: str, payload: dict, *, is_error: bool = False) -> TerraFinConversationMessage:
    content = {"toolName": "market_snapshot", "payload": payload}
    if is_error:
        content["isError"] = True
    return TerraFinConversationMessage(
        role="tool",
        name="market_snapshot",
        tool_call_id=call_id,
        content=json.dumps(content),
        metadata={"isError": is_error},
        blocks=(
            make_tool_result_block(
                call_id=call_id,
                tool_name="market_snapshot",
                capability_name="market_snapshot",
                execution_mode="invoke",
                payload=payload,
                is_error=is_error,
            ),
        ),
    )


def _tool_use_message(calls) -> TerraFinConversationMessage:
    return TerraFinConversationMessage(
        role="assistant",
        content="",
        metadata={"internalOnly": True, "internalToolUse": True},
        blocks=tuple(
            make_tool_use_block(
                call_id=call.call_id,
                tool_name=call.tool_name,
                arguments=call.arguments,
                provider_data=call.provider_data,
            )
            for call in calls
        ),
    )


def test_config_requires_an_api_key() -> None:
    with pytest.raises(TerraFinAnthropicModelConfigError, match="ANTHROPIC_API_KEY"):
        TerraFinAnthropicModelConfig.from_env({})
    with pytest.raises(TerraFinAnthropicModelConfigError, match="ANTHROPIC_API_KEY"):
        TerraFinAnthropicMessagesProvider(env={}).config

    config = TerraFinAnthropicModelConfig.from_env({"ANTHROPIC_API_KEY": "env-key"})
    assert config.api_key == "env-key"
    assert config.refusal_fallbacks is True
    assert config.effort == "high"


def test_config_reads_saved_api_key_and_rejects_unknown_effort(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_provider_credentials("anthropic", {"apiKey": "saved-anthropic-key"}, env)

    assert TerraFinAnthropicModelConfig.from_env(env).api_key == "saved-anthropic-key"
    with pytest.raises(TerraFinAnthropicModelConfigError, match="TERRAFIN_ANTHROPIC_EFFORT"):
        TerraFinAnthropicModelConfig.from_env({"ANTHROPIC_API_KEY": "key", "TERRAFIN_ANTHROPIC_EFFORT": "extreme"})


def test_request_puts_system_on_top_and_groups_parallel_tool_results() -> None:
    provider, client = _provider([_message([{"type": "text", "text": "Done."}])])
    calls = (
        make_tool_use_block(call_id="toolu_a", tool_name="market_snapshot", arguments={"name": "AAPL"}),
        make_tool_use_block(call_id="toolu_b", tool_name="market_snapshot", arguments={"name": "MSFT"}),
    )
    messages = [
        TerraFinConversationMessage(role="system", content="You are a hosted agent."),
        TerraFinConversationMessage(role="user", content="Compare AAPL and MSFT."),
        TerraFinConversationMessage(role="assistant", content="", blocks=calls),
        _tool_message("toolu_a", {"price": 1}),
        _tool_message("toolu_b", {"error": "boom"}, is_error=True),
    ]

    _complete(provider, messages)

    request = client.beta.messages.calls[0]
    assert request["system"].startswith("You are a hosted agent.")
    assert [message["role"] for message in request["messages"]] == ["user", "assistant", "user"]
    assert [block["id"] for block in request["messages"][1]["content"]] == ["toolu_a", "toolu_b"]
    results = request["messages"][2]["content"]
    assert [block["type"] for block in results] == ["tool_result", "tool_result"]
    assert [block["tool_use_id"] for block in results] == ["toolu_a", "toolu_b"]
    assert "is_error" not in results[0]
    assert results[1]["is_error"] is True
    assert request["tools"] == [
        {"name": "market_snapshot", "description": "Fetch snapshot.", "input_schema": _tool().input_schema}
    ]
    assert request["model"] == "claude-opus-5-5"
    assert request["thinking"]["type"] == "adaptive"
    assert request["output_config"] == {"effort": "high"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == [THINKING_BINDING_BETA, REFUSAL_FALLBACK_BETA]
    for forbidden in ("tool_choice", "temperature", "top_p", "top_k"):
        assert forbidden not in request


def test_refusal_fallbacks_can_be_turned_off_and_skip_unsupported_models() -> None:
    provider, client = _provider([_message([{"type": "text", "text": "Hi."}])], refusal_fallbacks=False)
    _complete(provider, [TerraFinConversationMessage(role="user", content="Hi")])
    assert "fallbacks" not in client.beta.messages.calls[0]
    assert REFUSAL_FALLBACK_BETA not in client.beta.messages.calls[0]["betas"]

    provider, client = _provider([_message([{"type": "text", "text": "Hi."}])])
    _complete(provider, [TerraFinConversationMessage(role="user", content="Hi")], model_id="claude-haiku-5-5")
    assert "fallbacks" not in client.beta.messages.calls[0]


def test_tool_ids_from_other_providers_are_made_valid() -> None:
    provider, client = _provider([_message([{"type": "text", "text": "Done."}])])
    messages = [
        TerraFinConversationMessage(role="user", content="AAPL?"),
        TerraFinConversationMessage(
            role="assistant",
            content="",
            blocks=(make_tool_use_block(call_id="gemini-call:0:abc", tool_name="market_snapshot", arguments={}),),
        ),
        _tool_message("gemini-call:0:abc", {"price": 1}),
    ]

    _complete(provider, messages)

    sent = client.beta.messages.calls[0]["messages"]
    assert sent[1]["content"][0]["id"] == "gemini-call_0_abc"
    assert sent[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "gemini-call_0_abc",
        "content": messages[2].content,
    }


def test_orphaned_tool_result_is_sent_as_text() -> None:
    provider, client = _provider([_message([{"type": "text", "text": "Done."}])])
    messages = [
        TerraFinConversationMessage(role="user", content="Go on."),
        _tool_message("toolu_gone", {"price": 1}),
    ]

    _complete(provider, messages)

    content = client.beta.messages.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "text"]
    assert content[1]["text"].startswith("[tool result: market_snapshot]")


def test_text_response_is_completed_and_keeps_thinking_out_of_metadata() -> None:
    provider, _ = _provider(
        [
            _message(
                [{"type": "thinking", "thinking": "", "signature": "sig-1"}, {"type": "text", "text": "AAPL is up."}]
            )
        ]
    )

    turn = _complete(provider, [TerraFinConversationMessage(role="user", content="AAPL?")])

    assert turn.stop_reason == "completed"
    assert turn.tool_calls == ()
    assert turn.assistant_message.content == "AAPL is up."
    # Message metadata is returned to API clients, so no content blocks ride on it.
    assert turn.assistant_message.metadata == {}


def test_tool_use_response_becomes_tool_calls() -> None:
    provider, _ = _provider(
        [
            _message(
                [
                    {"type": "text", "text": "Checking."},
                    {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {"name": "AAPL"}},
                    {"type": "tool_use", "id": "toolu_2", "name": "market_snapshot", "input": {"name": "MSFT"}},
                ],
                stop_reason="tool_use",
            )
        ]
    )

    turn = _complete(provider, [TerraFinConversationMessage(role="user", content="AAPL and MSFT?")])

    assert turn.stop_reason == "tool_calls"
    assert [(call.call_id, call.arguments) for call in turn.tool_calls] == [
        ("toolu_1", {"name": "AAPL"}),
        ("toolu_2", {"name": "MSFT"}),
    ]
    assert turn.assistant_message.content == "Checking."
    assert ANTHROPIC_CONTENT_KEY in turn.tool_calls[0].provider_data


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
@pytest.mark.parametrize(
    "content",
    [
        [
            {"type": "text", "text": "Partial answer"},
            {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {}},
        ],
        [{"type": "thinking", "thinking": "", "signature": "sig"}],
    ],
)
def test_cut_off_reply_is_an_error_with_or_without_text(stop_reason, content) -> None:
    provider, _ = _provider([_message(content, stop_reason=stop_reason)])

    with pytest.raises(TerraFinAnthropicModelResponseError, match=f"cut off.*{stop_reason}"):
        _complete(provider, [TerraFinConversationMessage(role="user", content="Long one.")])


def test_refusal_is_an_error_naming_its_category() -> None:
    provider, _ = _provider(
        [
            _message(
                [{"type": "text", "text": "I can start"}],
                stop_reason="refusal",
                stop_details={"type": "refusal", "category": "cyber", "explanation": None},
            )
        ]
    )

    with pytest.raises(TerraFinAnthropicModelResponseError, match="declined.*cyber"):
        _complete(provider, [TerraFinConversationMessage(role="user", content="?")])


def test_empty_reply_is_an_error() -> None:
    provider, _ = _provider([_message([{"type": "thinking", "thinking": "", "signature": "sig"}])])

    with pytest.raises(TerraFinAnthropicModelResponseError, match="empty reply"):
        _complete(provider, [TerraFinConversationMessage(role="user", content="?")])


def test_unhandled_stop_reason_is_an_error() -> None:
    provider, _ = _provider([_message([], stop_reason="pause_turn")])

    with pytest.raises(TerraFinAnthropicModelResponseError, match="pause_turn"):
        _complete(provider, [TerraFinConversationMessage(role="user", content="?")])


def test_thinking_blocks_are_replayed_unchanged_through_the_hosted_transcript() -> None:
    first_content = [
        {"type": "thinking", "thinking": "", "signature": "sig-think"},
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {"name": "AAPL"}},
    ]
    provider, client = _provider(
        [
            _message(first_content, stop_reason="tool_use"),
            _message([{"type": "thinking", "thinking": "", "signature": "sig-2"}, {"type": "text", "text": "Up 2%."}]),
            _message([{"type": "text", "text": "Ok."}]),
        ]
    )
    user = TerraFinConversationMessage(role="user", content="AAPL?", blocks=(make_text_block("AAPL?"),))
    first = _complete(provider, [user])

    # Record the turn the way the hosted loop does: the text, then the tool calls.
    conversation = TerraFinHostedConversation(
        session_id="anthropic:test",
        agent_name="market-researcher",
        messages=[
            user,
            TerraFinConversationMessage(
                role="assistant",
                content=first.assistant_message.content,
                blocks=(make_text_block(first.assistant_message.content),),
            ),
            _tool_use_message(first.tool_calls),
            _tool_message("toolu_1", {"price": 1}),
        ],
    )
    prepared = ContextBudgetManager(normalizer=TranscriptNormalizer()).prepare_messages(conversation, level="default")
    second = _complete(provider, prepared)

    replayed = client.beta.messages.calls[1]["messages"]
    assert [message["role"] for message in replayed] == ["user", "assistant", "user"]
    assert replayed[1]["content"] == first_content
    assert replayed[2]["content"][0]["tool_use_id"] == "toolu_1"

    conversation.messages.append(second.assistant_message)
    conversation.messages.append(TerraFinConversationMessage(role="user", content="Thanks."))
    _complete(provider, conversation.snapshot())

    third = client.beta.messages.calls[2]["messages"]
    assert third[1]["content"] == first_content
    # A final answer carries nothing, so it goes back as its text.
    assert third[3] == {"role": "assistant", "content": [{"type": "text", "text": "Up 2%."}]}


def test_compacted_turn_text_is_rebuilt_instead_of_replayed() -> None:
    long_text = "x" * 6000
    first_content = [
        {"type": "thinking", "thinking": "", "signature": "sig-think"},
        {"type": "text", "text": long_text},
        {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {"name": "AAPL"}},
    ]
    provider, client = _provider(
        [_message(first_content, stop_reason="tool_use"), _message([{"type": "text", "text": "Ok."}])]
    )
    user = TerraFinConversationMessage(role="user", content="AAPL?", blocks=(make_text_block("AAPL?"),))
    first = _complete(provider, [user])
    conversation = TerraFinHostedConversation(
        session_id="anthropic:test",
        agent_name="market-researcher",
        messages=[
            user,
            TerraFinConversationMessage(
                role="assistant",
                content=first.assistant_message.content,
                blocks=(make_text_block(first.assistant_message.content),),
            ),
            _tool_use_message(first.tool_calls),
            _tool_message("toolu_1", {"price": 1}),
        ],
    )
    prepared = ContextBudgetManager(normalizer=TranscriptNormalizer()).prepare_messages(conversation, level="minimal")
    compacted = next(message for message in prepared if message.role == "assistant" and message.content)
    assert len(compacted.content) < len(long_text)

    _complete(provider, prepared)

    sent = client.beta.messages.calls[1]["messages"][1]["content"]
    assert [block["type"] for block in sent] == ["text", "tool_use"]
    assert sent[0]["text"] == compacted.content
    assert sent[1]["id"] == "toolu_1"


def test_fallback_boundary_keeps_only_text_from_the_declined_model() -> None:
    provider, _ = _provider(
        [
            _message(
                [
                    {"type": "thinking", "thinking": "", "signature": "declined"},
                    {"type": "text", "text": "Partial."},
                    {
                        "type": "fallback",
                        "from": {"model": "claude-opus-5-5"},
                        "to": {"model": "claude-opus-4-8"},
                        "trigger": {"type": "refusal", "category": "cyber"},
                    },
                    {"type": "thinking", "thinking": "", "signature": "served"},
                    {"type": "text", "text": "Answer."},
                    {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {"name": "AAPL"}},
                ],
                stop_reason="tool_use",
            )
        ]
    )

    turn = _complete(provider, [TerraFinConversationMessage(role="user", content="?")])

    assert turn.tool_calls[0].provider_data[ANTHROPIC_CONTENT_KEY] == [
        {"type": "text", "text": "Partial."},
        {"type": "thinking", "thinking": "", "signature": "served"},
        {"type": "text", "text": "Answer."},
        {"type": "tool_use", "id": "toolu_1", "name": "market_snapshot", "input": {"name": "AAPL"}},
    ]


def _sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def test_real_sdk_stream_round_trip_without_network() -> None:
    """The adapter against the installed SDK's streaming client, served by a mock transport."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        body = _sse(
            [
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": "msg_1",
                            "type": "message",
                            "role": "assistant",
                            "model": "claude-opus-5-5",
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 10, "output_tokens": 1},
                        },
                    },
                ),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "signature_delta", "signature": "sig-stream"},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {"type": "tool_use", "id": "toolu_9", "name": "market_snapshot", "input": {}},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "input_json_delta", "partial_json": '{"name": "AAPL"}'},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 1}),
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                        "usage": {"output_tokens": 20},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    provider = TerraFinAnthropicMessagesProvider(
        config=TerraFinAnthropicModelConfig(api_key="test-key"), client=client
    )

    turn = _complete(provider, [TerraFinConversationMessage(role="user", content="AAPL?")])

    assert turn.stop_reason == "tool_calls"
    assert turn.tool_calls[0].arguments == {"name": "AAPL"}
    assert turn.tool_calls[0].provider_data[ANTHROPIC_CONTENT_KEY][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig-stream",
    }
    sent = json.loads(seen[0].content)
    assert sent["stream"] is True
    assert sent["fallbacks"] == "default"
    assert sent["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    beta_header = seen[0].headers["anthropic-beta"]
    assert REFUSAL_FALLBACK_BETA in beta_header and THINKING_BINDING_BETA in beta_header


def test_api_status_error_maps_to_response_error() -> None:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(
                    529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
                )
            )
        ),
    )
    provider = TerraFinAnthropicMessagesProvider(
        config=TerraFinAnthropicModelConfig(api_key="test-key"), client=client
    )

    with pytest.raises(TerraFinAnthropicModelResponseError, match="HTTP 529"):
        _complete(provider, [TerraFinConversationMessage(role="user", content="?")])


def test_resolve_model_rejects_models_without_adaptive_thinking_and_effort() -> None:
    provider = TerraFinAnthropicMessagesProvider(config=TerraFinAnthropicModelConfig(api_key="test-key"))

    assert provider.resolve_model("claude-sonnet-5-5").model_ref == "anthropic/claude-sonnet-5-5"
    with pytest.raises(TerraFinAnthropicModelConfigError, match="adaptive thinking"):
        provider.resolve_model("claude-haiku-4-5")


def test_prompt_too_long_triggers_the_prompt_budget_retry() -> None:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(
                    400,
                    json={
                        "type": "error",
                        "error": {
                            "type": "invalid_request_error",
                            "message": "prompt is too long: 1200000 tokens > 1000000 maximum",
                        },
                    },
                )
            )
        ),
    )
    provider = TerraFinAnthropicMessagesProvider(
        config=TerraFinAnthropicModelConfig(api_key="test-key"), client=client
    )

    with pytest.raises(TerraFinAnthropicModelResponseError) as raised:
        _complete(provider, [TerraFinConversationMessage(role="user", content="?")])
    assert is_prompt_budget_error(raised.value)
