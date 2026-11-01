import pytest

from TerraFin.agent.contracts.conversation import TerraFinTokenUsage
from TerraFin.agent.definitions import TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation
from TerraFin.agent.model_management import set_saved_provider_credentials
from TerraFin.agent.providers.google import (
    TerraFinGoogleModelConfig,
    TerraFinGoogleModelConfigError,
    TerraFinGoogleResponsesProvider,
)
from TerraFin.agent.runtime import TerraFinAgentSession
from TerraFin.agent.tools import TerraFinToolDefinition


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: float):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


def _agent_definition() -> TerraFinAgentDefinition:
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


def test_google_model_config_requires_api_key() -> None:
    with pytest.raises(TerraFinGoogleModelConfigError, match="GEMINI_API_KEY"):
        TerraFinGoogleModelConfig.from_env({})


def test_google_model_config_can_read_saved_api_key_from_model_state(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_provider_credentials("google", {"apiKey": "saved-google-key"}, env)

    config = TerraFinGoogleModelConfig.from_env(env)

    assert config.api_key == "saved-google-key"


def test_google_provider_serializes_tools_and_parses_function_calls() -> None:
    fake_session = _FakeSession(
        _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "market_snapshot",
                                        "args": {"name": "AAPL"},
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )
    )
    provider = TerraFinGoogleResponsesProvider(
        config=TerraFinGoogleModelConfig(api_key="gemini-key"),
        session=fake_session,
    )
    conversation = TerraFinHostedConversation(
        session_id="google:test",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="system", content="You are a hosted agent."),
            TerraFinConversationMessage(role="user", content="Give me AAPL."),
        ],
    )

    turn = provider.complete(
        model=provider.resolve_model("gemini-3.1-pro-preview"),
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="google:test"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert turn.stop_reason == "tool_calls"
    assert turn.tool_calls[0].tool_name == "market_snapshot"
    assert turn.tool_calls[0].arguments == {"name": "AAPL"}
    assert fake_session.calls[0]["url"].endswith("/models/gemini-3.1-pro-preview:generateContent")
    assert fake_session.calls[0]["json"]["tools"][0]["functionDeclarations"][0]["name"] == "market_snapshot"


def test_google_provider_renders_a_result_without_its_call_as_text() -> None:
    fake_session = _FakeSession(_FakeResponse({"candidates": [{"content": {"parts": [{"text": "Ok."}]}}]}))
    provider = TerraFinGoogleResponsesProvider(
        config=TerraFinGoogleModelConfig(api_key="gemini-key"),
        session=fake_session,
    )
    conversation = TerraFinHostedConversation(
        session_id="google:orphan",
        agent_name="market-researcher",
        messages=[
            TerraFinConversationMessage(role="user", content="Give me AAPL."),
            TerraFinConversationMessage(
                role="tool", name="market_snapshot", tool_call_id="cut-call", content='{"price": 1}'
            ),
        ],
    )

    provider.complete(
        model=provider.resolve_model("gemini-3.1-pro-preview"),
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="google:orphan"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    contents = fake_session.calls[0]["json"]["contents"]
    assert not any("functionResponse" in part for content in contents for part in content["parts"])
    assert contents[-1] == {"role": "user", "parts": [{"text": '[tool result: market_snapshot]\n{"price": 1}'}]}


def test_google_provider_reads_usage_metadata() -> None:
    fake_session = _FakeSession(
        _FakeResponse(
            {
                "candidates": [{"content": {"parts": [{"text": "Ok."}]}}],
                "usageMetadata": {
                    "promptTokenCount": 1200,
                    "cachedContentTokenCount": 800,
                    "candidatesTokenCount": 30,
                    "thoughtsTokenCount": 70,
                    "totalTokenCount": 1300,
                },
            }
        )
    )
    provider = TerraFinGoogleResponsesProvider(
        config=TerraFinGoogleModelConfig(api_key="gemini-key"),
        session=fake_session,
    )
    conversation = TerraFinHostedConversation(
        session_id="google:usage",
        agent_name="market-researcher",
        messages=[TerraFinConversationMessage(role="user", content="AAPL?")],
    )

    turn = provider.complete(
        model=provider.resolve_model("gemini-3.1-pro-preview"),
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="google:usage"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert turn.usage == TerraFinTokenUsage(input=1200, output=100, cache_read=800)
