from pathlib import Path

import pytest

import TerraFin.agent.providers.github_copilot as copilot_provider_module
from TerraFin.agent.definitions import TerraFinAgentDefinition
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedConversation
from TerraFin.agent.model_management import set_saved_provider_credentials
from TerraFin.agent.providers.github_copilot import (
    TerraFinGithubCopilotAuthError,
    TerraFinGithubCopilotConfig,
    TerraFinGithubCopilotConfigError,
    TerraFinGithubCopilotResponsesProvider,
    poll_github_copilot_device_access_token,
    request_github_copilot_device_code,
)
from TerraFin.agent.runtime import TerraFinAgentSession
from TerraFin.agent.tools import TerraFinToolDefinition


class _FakeTokenResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeRequestsSession:
    def __init__(
        self,
        get_response: _FakeTokenResponse | None = None,
        post_responses: list[_FakeTokenResponse] | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_responses = list(post_responses or [])
        self.calls: list[dict] = []

    def get(self, url: str, *, headers: dict, timeout: float):
        self.calls.append({"method": "get", "url": url, "headers": headers, "timeout": timeout})
        assert self.get_response is not None
        return self.get_response

    def post(self, url: str, *, headers: dict, data: dict, timeout: float):
        self.calls.append({"method": "post", "url": url, "headers": headers, "data": data, "timeout": timeout})
        assert self.post_responses
        return self.post_responses.pop(0)


class _FakeChatCompletionsAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "copilot-chat-1",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Copilot complete.",
                    },
                }
            ],
        }


class _FakeOpenAIClient:
    instances: list[dict] = []

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        default_headers: dict | None = None,
    ) -> None:
        self.chat = type("FakeChatNamespace", (), {"completions": _FakeChatCompletionsAPI()})()
        self.instances.append(
            {
                "api_key": api_key,
                "base_url": base_url,
                "timeout": timeout,
                "default_headers": dict(default_headers or {}),
                "client": self,
            }
        )


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


def test_copilot_config_requires_github_token() -> None:
    with pytest.raises(TerraFinGithubCopilotConfigError, match="COPILOT_GITHUB_TOKEN"):
        TerraFinGithubCopilotConfig.from_env({})


def test_copilot_config_can_read_saved_github_token_from_model_state(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_provider_credentials("github-copilot", {"githubToken": "ghu_saved_token"}, env)

    config = TerraFinGithubCopilotConfig.from_env(env)

    assert config.github_token == "ghu_saved_token"


def test_request_github_copilot_device_code_parses_response() -> None:
    session = _FakeRequestsSession(
        post_responses=[
            _FakeTokenResponse(
                {
                    "device_code": "device-code-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-EFGH",
                    "expires_in": 900,
                    "interval": 5,
                }
            )
        ]
    )

    device = request_github_copilot_device_code(session=session, timeout_seconds=12.0)

    assert device.device_code == "device-code-123"
    assert device.authorization_url.endswith("user_code=ABCD-EFGH")
    assert session.calls[0]["data"]["client_id"]
    assert session.calls[0]["timeout"] == 12.0


def test_poll_github_copilot_device_access_token_handles_pending_and_slow_down() -> None:
    session = _FakeRequestsSession(
        post_responses=[
            _FakeTokenResponse({"error": "authorization_pending"}),
            _FakeTokenResponse({"error": "slow_down"}),
            _FakeTokenResponse({"access_token": "gho_device_token", "token_type": "bearer"}),
        ]
    )
    sleep_calls: list[int] = []
    now_values = iter([0.0, 0.0, 1.0, 2.0])

    token = poll_github_copilot_device_access_token(
        device_code="device-code-123",
        interval_seconds=5,
        expires_in_seconds=900,
        session=session,
        sleep_fn=sleep_calls.append,
        now_fn=lambda: next(now_values),
    )

    assert token == "gho_device_token"
    assert sleep_calls == [5, 7]
    assert session.calls[2]["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"


def test_poll_github_copilot_device_access_token_raises_when_login_cancelled() -> None:
    session = _FakeRequestsSession(post_responses=[_FakeTokenResponse({"error": "access_denied"})])

    with pytest.raises(TerraFinGithubCopilotAuthError, match="cancelled"):
        poll_github_copilot_device_access_token(
            device_code="device-code-123",
            interval_seconds=5,
            expires_in_seconds=900,
            session=session,
            now_fn=lambda: 0.0,
        )


def test_copilot_provider_exchanges_token_uses_cache_and_runs_chat_completions(monkeypatch, tmp_path: Path) -> None:
    _FakeOpenAIClient.instances.clear()
    monkeypatch.setattr(copilot_provider_module, "OpenAI", _FakeOpenAIClient)
    token_session = _FakeRequestsSession(
        get_response=_FakeTokenResponse(
            {
                "token": "copilot-token;proxy-ep=proxy.individual.githubcopilot.com;",
                "expires_at": 4_102_444_800,
            }
        )
    )
    provider = TerraFinGithubCopilotResponsesProvider(
        config=TerraFinGithubCopilotConfig(
            github_token="ghu_test_token",
            token_cache_path=str(tmp_path / "copilot-token.json"),
        ),
        session=token_session,
    )
    info_one = provider._resolve_api_token()
    info_two = provider._resolve_api_token()
    conversation = TerraFinHostedConversation(
        session_id="copilot:test",
        agent_name="market-researcher",
        messages=[TerraFinConversationMessage(role="user", content="hello")],
    )

    turn = provider.complete(
        model=provider.resolve_model("gpt-4o"),
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="copilot:test"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert info_one["baseUrl"] == "https://api.individual.githubcopilot.com"
    assert info_two["token"] == info_one["token"]
    assert len(token_session.calls) == 1
    assert token_session.calls[0]["headers"]["Authorization"] == "Bearer ghu_test_token"
    assert _FakeOpenAIClient.instances[0]["base_url"] == "https://api.individual.githubcopilot.com"
    assert _FakeOpenAIClient.instances[0]["api_key"].startswith("copilot-token;proxy-ep=")
    assert _FakeOpenAIClient.instances[0]["default_headers"]["Editor-Version"] == "vscode/1.96.2"
    assert _FakeOpenAIClient.instances[0]["default_headers"]["User-Agent"] == "GitHubCopilotChat/0.26.7"
    assert _FakeOpenAIClient.instances[0]["client"].chat.completions.calls[0]["model"] == "gpt-4o"
    assert turn.assistant_message is not None
    assert turn.assistant_message.content == "Copilot complete."


def test_copilot_provider_parses_tool_calls_from_chat_completions(monkeypatch, tmp_path: Path) -> None:
    _FakeOpenAIClient.instances.clear()

    class _ToolCallClient(_FakeOpenAIClient):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)

            def _create(**payload):
                self.chat.completions.calls.append(payload)
                return {
                    "id": "copilot-chat-tools-1",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_123",
                                        "type": "function",
                                        "function": {
                                            "name": "market_snapshot",
                                            "arguments": "{\"name\":\"AAPL\"}",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }

            self.chat = type(
                "FakeChatNamespace",
                (),
                {"completions": type("FakeCompletions", (), {"calls": [], "create": staticmethod(_create)})()},
            )()

    monkeypatch.setattr(copilot_provider_module, "OpenAI", _ToolCallClient)
    token_session = _FakeRequestsSession(
        get_response=_FakeTokenResponse(
            {
                "token": "copilot-token;proxy-ep=proxy.individual.githubcopilot.com;",
                "expires_at": 4_102_444_800,
            }
        )
    )
    provider = TerraFinGithubCopilotResponsesProvider(
        config=TerraFinGithubCopilotConfig(
            github_token="ghu_test_token",
            token_cache_path=str(tmp_path / "copilot-token.json"),
        ),
        session=token_session,
    )
    conversation = TerraFinHostedConversation(
        session_id="copilot:test",
        agent_name="market-researcher",
        messages=[TerraFinConversationMessage(role="user", content="hello")],
    )

    turn = provider.complete(
        model=provider.resolve_model("gpt-4o"),
        agent=_agent_definition(),
        session=TerraFinAgentSession(session_id="copilot:test"),
        conversation=conversation,
        messages=conversation.snapshot(),
        tools=(_tool(),),
    )

    assert turn.assistant_message is None
    assert turn.stop_reason == "tool_calls"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool_name == "market_snapshot"
    assert turn.tool_calls[0].arguments == {"name": "AAPL"}


def test_copilot_provider_rejects_non_openai_model_families() -> None:
    provider = TerraFinGithubCopilotResponsesProvider(
        config=TerraFinGithubCopilotConfig(github_token="ghu_test_token"),
    )

    with pytest.raises(TerraFinGithubCopilotConfigError, match="OpenAI-compatible Copilot family"):
        provider.resolve_model("claude-sonnet-4.5")


def test_copilot_provider_uses_shared_state_dir_for_default_token_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TERRAFIN_STATE_DIR", str(tmp_path / "state"))
    provider = TerraFinGithubCopilotResponsesProvider(
        config=TerraFinGithubCopilotConfig(github_token="ghu_test_token"),
    )

    assert provider._resolve_token_cache_path() == tmp_path / "state" / "credentials" / "github-copilot.token.json"
