import json

import pytest
from datetime import UTC, datetime, timedelta

from openai import APIError

from TerraFin.agent.definitions import TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation
from TerraFin.agent.openai_model import (
    TerraFinOpenAIConfigError,
    TerraFinOpenAIModelConfig,
    TerraFinOpenAIResponsesModelClient,
)
from TerraFin.agent.runtime import TerraFinAgentSession
from TerraFin.agent.tools import TerraFinToolDefinition


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def model_dump(self, mode="python"):
        _ = mode
        return self._payload


class _FakeResponsesAPI:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = _FakeResponsesAPI(responses)


def _agent_definition() -> TerraFinAgentDefinition:
    return TerraFinAgentDefinition(
        name="market-researcher",
        description="General market agent.",
        allowed_capabilities=("market_snapshot", "open_chart"),
        chart_access=True,
        allow_background_tasks=True,
    )


def _tool() -> TerraFinToolDefinition:
    return TerraFinToolDefinition(
        name="market_snapshot",
        capability_name="market_snapshot",
        description="Fetch snapshot.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"]},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        execution_mode="invoke",
    )


def _watermark_after(conversation, index: int) -> None:
    """Pin providerState's watermark just after messages[index]."""
    state = conversation.metadata.setdefault("providerState", {}).setdefault("openai", {})
    # Restamp deterministically first. utc_now() can return the same value for two
    # messages, and the resume boundary is a strict >, so a real-clock watermark
    # intermittently drops the message after it — that flake failed 1 run in 7.
    base = datetime(2026, 9, 3, 1, 0, 0, tzinfo=UTC)
    for offset, message in enumerate(conversation.messages):
        stamp = base + timedelta(seconds=offset)
        try:
            message.created_at = stamp
        except Exception:  # frozen dataclass
            object.__setattr__(message, "created_at", stamp)
    state["sentThrough"] = (base + timedelta(seconds=index)).isoformat()
    state.setdefault("openCallIds", [])
    state.setdefault("responseId", conversation.metadata.get("openai_response_id"))


def test_openai_model_config_requires_api_key() -> None:
    with pytest.raises(TerraFinOpenAIConfigError, match="OPENAI_API_KEY"):
        TerraFinOpenAIModelConfig.from_env({})


def test_complete_parses_function_calls_from_openai_response() -> None:
    fake_client = _FakeClient(
        [
            _FakeResponse(
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "market_snapshot",
                            "arguments": json.dumps({"name": "AAPL"}),
                        }
                    ],
                }
            )
        ]
    )
    client = TerraFinOpenAIResponsesModelClient(
        config=TerraFinOpenAIModelConfig(api_key="test-key"),
        client=fake_client,
    )
    conversation = TerraFinHostedConversation(
        session_id="conv_1",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="Give me an AAPL snapshot."),
        ],
    )

    turn = client.complete(
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="conv_1"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert turn.stop_reason == "tool_calls"
    assert turn.assistant_message is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool_name == "market_snapshot"
    assert turn.tool_calls[0].arguments == {"name": "AAPL"}

    payload = fake_client.responses.calls[0]
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "market_snapshot"
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["role"] == "user"
    assert conversation.metadata["openai_response_id"] == "resp_1"


def test_complete_uses_previous_response_id_and_tool_outputs_on_followup() -> None:
    fake_client = _FakeClient(
        [
            _FakeResponse(
                {
                    "id": "resp_2",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Snapshot complete."}],
                        }
                    ],
                    "output_text": "Snapshot complete.",
                }
            )
        ]
    )
    client = TerraFinOpenAIResponsesModelClient(
        config=TerraFinOpenAIModelConfig(api_key="test-key"),
        client=fake_client,
    )
    conversation = TerraFinHostedConversation(
        session_id="conv_2",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="Give me an AAPL snapshot."),
            TerraFinConversationMessage(role="assistant", content="I'll check."),
            TerraFinConversationMessage(
                role="tool",
                name="market_snapshot",
                tool_call_id="call_1",
                content='{"payload":{"ticker":"AAPL"}}',
            ),
        ],
        metadata={
            "openai_response_id": "resp_1",
            "openai_message_cursor": 2,
        },
    )
    _watermark_after(conversation, 1)

    turn = client.complete(
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="conv_2"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert turn.stop_reason == "completed"
    assert turn.assistant_message is not None
    assert turn.assistant_message.content == "Snapshot complete."
    payload = fake_client.responses.calls[0]
    assert payload["previous_response_id"] == "resp_1"
    assert "instructions" not in payload
    assert payload["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"payload":{"ticker":"AAPL"}}',
        }
    ]


def _responses(count: int) -> _FakeClient:
    return _FakeClient(
        [
            _FakeResponse({"id": f"resp_new{i}", "output": [], "output_text": "Done."})
            for i in range(1, count + 1)
        ]
    )


def _client(fake: _FakeClient) -> TerraFinOpenAIResponsesModelClient:
    return TerraFinOpenAIResponsesModelClient(
        config=TerraFinOpenAIModelConfig(api_key="test-key"), client=fake
    )


def _run(client, conversation) -> None:
    client.complete(
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id=conversation.session_id),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )


def _poisoned_conversation() -> TerraFinHostedConversation:
    """The shape of the real failure: an assistant turn whose tool calls were
    persisted but whose results never were, then a new user message."""
    return TerraFinHostedConversation(
        session_id="conv_poisoned",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="30Y yield outlook?"),
            TerraFinConversationMessage(role="assistant", content="Checking."),
            TerraFinConversationMessage(
                role="tool",
                name="resolve",
                tool_call_id="call_EMQJ",
                content='{"ok":true}',
            ),
            TerraFinConversationMessage(role="assistant", content=""),
            TerraFinConversationMessage(role="user", content="야"),
        ],
        metadata={
            "toolCallHistory": [
                {"callId": "call_EMQJ", "toolName": "resolve"},
                {"callId": "call_2vS5", "toolName": "market_snapshot"},
                {"callId": "call_MCD8", "toolName": "market_snapshot"},
            ],
            "openai_response_id": "resp_0c61",
            "openai_message_cursor": 5,
        },
    )


def test_unanswerable_chain_is_abandoned_and_recorded() -> None:
    fake = _responses(1)
    conversation = _poisoned_conversation()
    _run(_client(fake), conversation)

    payload = fake.responses.calls[0]
    assert "previous_response_id" not in payload
    state = conversation.metadata["providerState"]["openai"]
    assert state["openCallIds"] == [], "the dead chain's open calls must be cleared"
    assert state["responseId"] == "resp_new1"


def test_fresh_chain_keeps_tool_output_as_text() -> None:
    fake = _responses(1)
    conversation = _poisoned_conversation()
    _run(_client(fake), conversation)

    payload = fake.responses.calls[0]
    assert not [item for item in payload["input"] if item.get("type") == "function_call_output"]
    texts = [
        block["text"]
        for item in payload["input"]
        if item.get("type") == "message"
        for block in item.get("content", [])
    ]
    assert any('[tool result: resolve]' in text and '{"ok":true}' in text for text in texts)


def test_next_turn_resumes_normally_after_an_abandonment() -> None:
    """Abandonment must not pin the session to full replay for life."""
    fake = _responses(2)
    client = _client(fake)
    conversation = _poisoned_conversation()
    _run(client, conversation)

    conversation.messages.append(
        TerraFinConversationMessage(role="assistant", content="Here is the answer.")
    )
    conversation.messages.append(TerraFinConversationMessage(role="user", content="And TLT?"))
    _run(client, conversation)

    assert fake.responses.calls[1]["previous_response_id"] == "resp_new1"


def test_refusal_response_does_not_replay_a_consumed_tool_output() -> None:
    """A response with no text and no tool calls advances responseId but appends no
    assistant message.
    """
    fake = _FakeClient(
        [
            _FakeResponse({"id": "resp_call", "output": [
                {"type": "function_call", "call_id": "call_A", "name": "market_snapshot", "arguments": "{}"}
            ]}),
            _FakeResponse({"id": "resp_refusal", "output": [], "output_text": ""}),
            _FakeResponse({"id": "resp_final", "output": [], "output_text": "Done."}),
        ]
    )
    client = _client(fake)
    conversation = TerraFinHostedConversation(
        session_id="conv_refusal",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="30Y yield outlook?"),
        ],
        metadata={},
    )
    _run(client, conversation)  # asks for call_A
    conversation.messages.append(
        TerraFinConversationMessage(
            role="tool", name="market_snapshot", tool_call_id="call_A", content='{"px":1}'
        )
    )
    _run(client, conversation)  # refusal: no text, no calls, nothing appended
    conversation.messages.append(TerraFinConversationMessage(role="user", content="and TLT?"))
    _run(client, conversation)

    replayed = [
        item for item in fake.responses.calls[2]["input"] if item.get("type") == "function_call_output"
    ]
    assert not replayed, f"re-sent an already-consumed tool output: {replayed}"
    assert fake.responses.calls[2]["previous_response_id"] == "resp_refusal"


def test_open_call_ids_are_recorded_from_the_response_that_made_them() -> None:
    fake = _FakeClient(
        [
            _FakeResponse({"id": "resp_call", "output": [
                {"type": "function_call", "call_id": "call_A", "name": "market_snapshot", "arguments": "{}"},
                {"type": "function_call", "call_id": "call_B", "name": "market_snapshot", "arguments": "{}"},
            ]})
        ]
    )
    conversation = TerraFinHostedConversation(
        session_id="conv_open",
        agent_name="market-researcher",
        messages=[TerraFinConversationMessage(role="user", content="30Y?")],
        metadata={},
    )
    _run(_client(fake), conversation)
    assert conversation.metadata["providerState"]["openai"]["openCallIds"] == ["call_A", "call_B"]


def test_expired_response_id_recovers_on_a_fresh_chain() -> None:
    """No bookkeeping can predict an expired or pruned response id, so a 400 that
    says the chain is unusable must be recovered from, not raised."""
    fake = _RaisingClient(
        [_FakeAPIError("Previous response with id 'resp_1' not found.")],
        [_FakeResponse({"id": "resp_new", "output": [], "output_text": "Done."})],
    )
    conversation = TerraFinHostedConversation(
        session_id="conv_expired",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="30Y?"),
            # Something new to say, so a resume is genuinely attempted on the dead id.
            TerraFinConversationMessage(role="user", content="and TLT?"),
        ],
        metadata={"openai_response_id": "resp_1", "openai_message_cursor": 2},
    )
    _watermark_after(conversation, 1)

    _run(_client(fake), conversation)

    assert len(fake.responses.calls) == 2, "the dead chain was not retried"
    assert fake.responses.calls[0]["previous_response_id"] == "resp_1"
    assert "previous_response_id" not in fake.responses.calls[1]
    assert conversation.metadata["openai_response_id"] == "resp_new"


def test_over_budget_resume_sends_the_approved_copy_not_the_raw_one() -> None:
    """A resume message that is not byte-identical to the budget manager's approved copy
    would bypass the prompt budget, so the chain is dropped instead.
    """
    from TerraFin.agent.models.providers.openai_compatible import OpenAICompatibleResponsesRunner

    runner = OpenAICompatibleResponsesRunner(
        provider_id="openai", max_retries=0, response_error_cls=RuntimeError
    )
    raw = '{"payload":"' + "x" * 20000 + '"}'
    conversation = TerraFinHostedConversation(
        session_id="conv_big",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="user", content="30Y?"),
            TerraFinConversationMessage(
                role="tool", name="market_snapshot", tool_call_id="call_A", content=raw
            ),
        ],
        metadata={
            "openai_response_id": "resp_1",
            "openai_message_cursor": 1,
            "providerState": {
                "openai": {"responseId": "resp_1", "openCallIds": ["call_A"]}
            },
        },
    )
    _watermark_after(conversation, 0)
    prepared = (
        TerraFinConversationMessage(role="user", content="30Y?"),
        TerraFinConversationMessage(
            role="tool", name="market_snapshot", tool_call_id="call_A", content='{"payload":"SHORT"}'
        ),
    )

    payload = runner._build_request_payload(
        model_id="gpt-test",
        agent=_agent_definition(),
        conversation=conversation,
        messages=prepared,
        tools=(_tool(),),
        legacy_response_id="resp_1",
        legacy_message_cursor=1,
        legacy_response_id_key="openai_response_id",
    )

    # The chain is kept; what changes is that the wire carries the budget
    # manager's approved copy, never the raw message behind the cursor.
    assert payload["previous_response_id"] == "resp_1"
    wire = json.dumps(payload["input"])
    assert raw not in wire, "sent the uncompacted message anyway"
    assert "SHORT" in wire, "lost the tool data entirely"


def test_in_budget_resume_still_continues_the_chain() -> None:
    """The gate must not abandon every chain: identical content resumes normally."""
    from TerraFin.agent.models.providers.openai_compatible import OpenAICompatibleResponsesRunner

    runner = OpenAICompatibleResponsesRunner(
        provider_id="openai", max_retries=0, response_error_cls=RuntimeError
    )
    # Stamp explicitly: default created_at follows construction order, and building
    # the tool message first would date it before the user turn.
    user_message = _stamped("user", "30Y?", 10)
    tool_message = _stamped(
        "tool", '{"px":1}', 20, name="market_snapshot", tool_call_id="call_A"
    )
    conversation = TerraFinHostedConversation(
        session_id="conv_ok",
        agent_name="market-researcher",
        messages=[user_message, tool_message],
        metadata={
            "openai_response_id": "resp_1",
            "openai_message_cursor": 1,
            "providerState": {
                "openai": {"responseId": "resp_1", "messageCursor": 1, "openCallIds": ["call_A"]}
            },
        },
    )
    _watermark_after(conversation, 0)

    payload = runner._build_request_payload(
        model_id="gpt-test",
        agent=_agent_definition(),
        conversation=conversation,
        messages=(user_message, tool_message),
        tools=(_tool(),),
        legacy_response_id="resp_1",
        legacy_message_cursor=1,
        legacy_response_id_key="openai_response_id",
    )

    assert payload["previous_response_id"] == "resp_1"
    outputs = [item for item in payload["input"] if item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in outputs] == ["call_A"]


def test_fresh_chain_replays_assistant_turns_in_the_assistant_role() -> None:
    fake = _responses(1)
    conversation = _poisoned_conversation()
    conversation.messages.insert(
        4, TerraFinConversationMessage(role="assistant", content="ANSWER-ONE: 30Y at 4.7%.")
    )
    _run(_client(fake), conversation)

    replayed = [
        item["content"]
        for item in fake.responses.calls[0]["input"]
        if item.get("role") == "assistant"
    ]
    assert "ANSWER-ONE: 30Y at 4.7%." in replayed, "assistant history erased on a fresh chain"
    assert all(item for item in replayed), "empty assistant turns must not be replayed"


class _FakeAPIError(APIError):
    """Minimal stand-in: the runner only reads str(exc) and .status_code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        Exception.__init__(self, message)
        self.message = message
        self.status_code = status_code


class _RaisingResponsesAPI:
    def __init__(self, errors: list, responses: list[_FakeResponse]) -> None:
        self.errors = list(errors)
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0)


class _RaisingClient:
    def __init__(self, errors: list, responses: list[_FakeResponse]) -> None:
        self.responses = _RaisingResponsesAPI(errors, responses)


def _stamped(role: str, content: str, second: int, **kw):
    from datetime import UTC, datetime

    return TerraFinConversationMessage(
        role=role, content=content, created_at=datetime(2026, 9, 3, 1, 0, second, tzinfo=UTC), **kw
    )


def _runner():
    from TerraFin.agent.models.providers.openai_compatible import OpenAICompatibleResponsesRunner

    return OpenAICompatibleResponsesRunner(
        provider_id="openai", max_retries=0, response_error_cls=RuntimeError
    )


def test_in_place_note_deletion_does_not_drop_a_message_from_the_resume() -> None:
    """loop.py:511-516 deletes the prior working-memory note from conversation.messages in
    place, so an absolute index omits one message — a deferred research report, which is
    never redelivered once its marker clears.
    """
    report = _stamped("user", "[BACKGROUND REPORT] deep research finished", 30)
    messages = [
        _stamped("system", "sys", 0),
        _stamped("user", "Q1", 10),
        report,
        _stamped("user", "[Automated system note - WorkingMemory] fresh", 40),
        _stamped("user", "Q2", 50),
    ]
    conversation = TerraFinHostedConversation(
        session_id="conv_wm",
        agent_name="market-researcher",
        messages=messages,
        metadata={
            "providerState": {
                "openai": {
                    "responseId": "resp_1",
                    "openCallIds": [],
                    "sentThrough": "2026-09-03T01:00:20+00:00",
                }
            }
        },
    )

    payload = _runner()._build_request_payload(
        model_id="gpt-test",
        agent=_agent_definition(),
        conversation=conversation,
        messages=tuple(messages),
        tools=(_tool(),),
        legacy_response_id="resp_1",
        legacy_message_cursor=3,
        legacy_response_id_key="openai_response_id",
    )

    wire = json.dumps(payload["input"], ensure_ascii=False)
    assert "BACKGROUND REPORT" in wire, "the report was dropped from the resume"
    assert "Q2" in wire


def test_nothing_new_starts_a_fresh_chain_instead_of_an_empty_request() -> None:
    """An empty resume slice previously continued the chain with input: [], so the
    user's question never reached the model."""
    messages = [_stamped("system", "sys", 0), _stamped("user", "Q1", 10)]
    conversation = TerraFinHostedConversation(
        session_id="conv_empty",
        agent_name="market-researcher",
        messages=messages,
        metadata={
            "providerState": {
                "openai": {
                    "responseId": "resp_1",
                    "openCallIds": [],
                    "sentThrough": "2026-09-03T01:00:59+00:00",
                }
            }
        },
    )

    payload = _runner()._build_request_payload(
        model_id="gpt-test",
        agent=_agent_definition(),
        conversation=conversation,
        messages=tuple(messages),
        tools=(_tool(),),
        legacy_response_id="resp_1",
        legacy_message_cursor=2,
        legacy_response_id_key="openai_response_id",
    )

    assert "previous_response_id" not in payload
    assert payload["input"], "sent an empty request"
    assert "Q1" in json.dumps(payload["input"], ensure_ascii=False)


def test_dead_chain_is_classified_structurally_not_by_provider_prose() -> None:
    """The three English phrases this used to grep for are not a contract. A 400 on
    a request that carried previous_response_id is what makes it recoverable."""
    runner = _runner()
    assert runner._is_dead_chain_error(_FakeAPIError("Error code: 400 - anything", 400), sent_chain=True)
    assert not runner._is_dead_chain_error(
        _FakeAPIError("Error code: 400 - anything", 400), sent_chain=False
    ), "a 400 with no chain to abandon is not a chain error"
    assert not runner._is_dead_chain_error(
        _FakeAPIError("Error code: 500 - No tool output found for function call call_A", 500),
        sent_chain=True,
    ), "a 5xx must stay retryable as a 5xx"


def test_recovery_strikes_survive_a_turn_that_did_not_resume() -> None:
    """Resetting on any success cleared the count on the very next non-resumed
    turn, so a permanently broken resume oscillated 2-1-2-1 requests forever."""
    runner = _runner()
    after_recovery = runner._next_recoveries({}, attempted_resume=True, recovered_chain=True)
    assert after_recovery == 1
    # The next turn cannot resume (the recovery cleared the chain), so the count
    # must hold — decaying it here would mean the limit is never reachable.
    assert (
        runner._next_recoveries(
            {"chainRecoveries": after_recovery}, attempted_resume=False, recovered_chain=False
        )
        == after_recovery
    ), "a non-resumed success must not clear the strikes"
    # A resume that actually ran and worked clears it.
    assert (
        runner._next_recoveries(
            {"chainRecoveries": after_recovery}, attempted_resume=True, recovered_chain=False
        )
        == 0
    )


def test_a_session_past_its_strike_limit_stops_resuming() -> None:
    messages = [_stamped("user", "Q1", 10), _stamped("user", "Q2", 20)]
    conversation = TerraFinHostedConversation(
        session_id="conv_struck",
        agent_name="market-researcher",
        messages=messages,
        metadata={
            "providerState": {
                "openai": {
                    "responseId": "resp_1",
                    "openCallIds": [],
                    "sentThrough": "2026-09-03T01:00:15+00:00",
                    "chainRecoveries": 2,
                }
            }
        },
    )

    payload = _runner()._build_request_payload(
        model_id="gpt-test",
        agent=_agent_definition(),
        conversation=conversation,
        messages=tuple(messages),
        tools=(_tool(),),
        legacy_response_id="resp_1",
        legacy_message_cursor=0,
        legacy_response_id_key="openai_response_id",
    )

    assert "previous_response_id" not in payload, "kept resuming a chain that keeps failing"


def test_recovery_strikes_expire_so_one_bad_400_does_not_disable_resume_forever() -> None:
    """Holding the count made it a permanent latch: at the limit no resume is
    attempted, so nothing could ever clear it. Strikes expire on wall clock."""
    from datetime import UTC, datetime, timedelta

    runner = _runner()
    fresh = {
        "chainRecoveries": 2,
        "chainRecoveriesAt": datetime.now(UTC).isoformat(),
    }
    stale = {
        "chainRecoveries": 2,
        "chainRecoveriesAt": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    }
    assert runner._strikes_active(fresh), "recent strikes must suppress resuming"
    assert not runner._strikes_active(stale), "hour-old strikes must not suppress forever"
    assert not runner._strikes_active({"chainRecoveries": 1})


def test_turn_unfinished_is_scoped_to_the_newest_turn() -> None:
    """A whole-conversation diff stayed >=1 forever after one abort: the orphan tool_use
    survives normalize at for_model=False and _abandon_chain clears only provider state.
    """
    from TerraFin.agent.contracts.conversation import make_text_block, make_tool_use_block
    from TerraFin.interface.agent.data_routes import _turn_unfinished

    def _Conv(messages=()):
        return tuple(messages)

    def asked(call_id: str):
        return TerraFinConversationMessage(
            role="assistant",
            content="Checking.",
            blocks=(make_tool_use_block(call_id=call_id, tool_name="market_snapshot", arguments={}),),
        )

    def answered(call_id: str):
        return TerraFinConversationMessage(
            role="tool", name="market_snapshot", tool_call_id=call_id, content='{"px":1}'
        )

    plain = TerraFinConversationMessage(
        role="assistant", content="Done.", blocks=(make_text_block("Done."),)
    )

    assert _turn_unfinished(_Conv([asked("c1")])), "a turn that died mid-tool must be visible"
    assert not _turn_unfinished(_Conv([asked("c1"), answered("c1")]))
    assert not _turn_unfinished(_Conv([plain]))
    assert not _turn_unfinished(None)
    # An old orphan followed by a healthy call must not report interrupted.
    assert not _turn_unfinished(
        _Conv([asked("old"), asked("c2"), answered("c2"), plain])
    ), "an old abandoned call must not pin this true"




def test_a_turn_that_answered_is_not_reported_unfinished() -> None:
    """The recovery tracker returns 200 mid-way through parallel tool calls
    (loop.py:349-360), orphaning the rest.
    """
    from TerraFin.agent.contracts.conversation import make_text_block, make_tool_use_block
    from TerraFin.interface.agent.data_routes import _turn_unfinished

    def _Conv(messages=()):
        return tuple(messages)

    asked_two = TerraFinConversationMessage(
        role="assistant",
        content="",
        blocks=(
            make_tool_use_block(call_id="call_A", tool_name="market_snapshot", arguments={}),
            make_tool_use_block(call_id="call_B", tool_name="market_snapshot", arguments={}),
        ),
    )
    answered_a = TerraFinConversationMessage(
        role="tool", name="market_snapshot", tool_call_id="call_A", content='{"px":1}'
    )
    fallback = TerraFinConversationMessage(
        role="assistant",
        content="I could not complete that lookup, here is what I have.",
        blocks=(make_text_block("I could not complete that lookup, here is what I have."),),
    )

    assert _turn_unfinished(
        _Conv([TerraFinConversationMessage(role="user", content="Q"), asked_two, answered_a])
    ), "a genuine death mid-tool must still be reported"
    assert not _turn_unfinished(
        _Conv([
            TerraFinConversationMessage(role="user", content="Q"),
            asked_two,
            answered_a,
            fallback,
        ])
    ), "an answered turn must not be branded interrupted"


def test_unfinished_detection_uses_the_real_carrier_shape() -> None:
    """Pins the check order against production shapes, not fixture shapes."""
    from TerraFin.agent.contracts.conversation import make_text_block, make_tool_use_block
    from TerraFin.interface.agent.data_routes import _turn_unfinished

    def _Conv(messages=()):
        return tuple(messages)

    question = TerraFinConversationMessage(role="user", content="30Y outlook?")
    preamble = TerraFinConversationMessage(
        role="assistant",
        content="Let me pull the filings.",
        blocks=(make_text_block("Let me pull the filings."),),
    )
    # The real carrier: no content, internalOnly, blocks only.
    carrier = TerraFinConversationMessage(
        role="assistant",
        content="",
        metadata={"internalOnly": True, "internalToolUse": True},
        blocks=(make_tool_use_block(call_id="call_A", tool_name="market_snapshot", arguments={}),),
    )
    result = TerraFinConversationMessage(
        role="tool", name="market_snapshot", tool_call_id="call_A", content='{"px":1}'
    )
    answer = TerraFinConversationMessage(
        role="assistant", content="5.27%.", blocks=(make_text_block("5.27%."),)
    )

    assert _turn_unfinished(
        _Conv([question, preamble, carrier])
    ), "died after the carrier was persisted and before its result"
    assert not _turn_unfinished(_Conv([question, preamble, carrier, result, answer]))


def test_a_turn_that_died_between_tool_cycles_is_reported_unfinished() -> None:
    """The window an unanswered-call check cannot see."""
    from TerraFin.agent.contracts.conversation import make_text_block, make_tool_use_block
    from TerraFin.interface.agent.data_routes import _turn_unfinished

    def _Conv(messages=()):
        return tuple(messages)

    question = TerraFinConversationMessage(role="user", content="30Y outlook?")
    preamble = TerraFinConversationMessage(
        role="assistant",
        content="Let me pull the financials.",
        blocks=(make_text_block("Let me pull the financials."),),
    )
    carrier = TerraFinConversationMessage(
        role="assistant",
        content="",
        metadata={"internalOnly": True, "internalToolUse": True},
        blocks=(make_tool_use_block(call_id="call_A", tool_name="market_snapshot", arguments={}),),
    )
    result = TerraFinConversationMessage(
        role="tool", name="market_snapshot", tool_call_id="call_A", content='{"px":1}'
    )
    answer = TerraFinConversationMessage(
        role="assistant", content="5.27%.", blocks=(make_text_block("5.27%."),)
    )

    # Every call answered, but the turn never produced an answer.
    assert _turn_unfinished(
        _Conv([question, preamble, carrier, result])
    ), "a death between tool cycles must be reported"
    assert not _turn_unfinished(_Conv([question, preamble, carrier, result, answer]))


def test_turn_unfinished_names_which_death() -> None:
    """The three deaths need different advice: a tool call left without its result, data
    gathered but no answer, or nothing gathered at all.
    """
    from TerraFin.agent.contracts.conversation import make_text_block, make_tool_use_block
    from TerraFin.interface.agent.data_routes import _turn_unfinished

    def _Conv(messages=()):
        return tuple(messages)

    question = TerraFinConversationMessage(role="user", content="30Y outlook?")
    preamble = TerraFinConversationMessage(
        role="assistant", content="Checking.", blocks=(make_text_block("Checking."),)
    )
    carrier = TerraFinConversationMessage(
        role="assistant",
        content="",
        metadata={"internalOnly": True, "internalToolUse": True},
        blocks=(make_tool_use_block(call_id="call_A", tool_name="market_snapshot", arguments={}),),
    )
    result = TerraFinConversationMessage(
        role="tool", name="market_snapshot", tool_call_id="call_A", content='{"px":1}'
    )
    answer = TerraFinConversationMessage(
        role="assistant", content="5.27%.", blocks=(make_text_block("5.27%."),)
    )

    assert _turn_unfinished(_Conv([question, preamble, carrier])) == "mid-tool"
    assert _turn_unfinished(_Conv([question, preamble, carrier, result])) == "mid-turn"
    assert _turn_unfinished(_Conv([question])) == "no-answer"
    assert _turn_unfinished(_Conv([question, preamble, carrier, result, answer])) is None
