import json

import pytest

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
