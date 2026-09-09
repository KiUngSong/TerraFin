import json

import TerraFin.agent.cli as agent_cli
from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME


class _FakeClient:
    def __init__(self, *, transport: str = "auto", base_url: str | None = None, timeout: float = 10.0) -> None:
        self.transport = transport
        self.base_url = base_url
        self.timeout = timeout

    def resolve(self, query: str):
        return {"query": query, "transport": self.transport}

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily"):
        raise RuntimeError(f"boom:{name}:{depth}:{view}")

    def runtime_agents(self):
        return {"agents": [{"name": DEFAULT_HOSTED_AGENT_NAME}]}

    def runtime_create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        metadata: dict | None = None,
    ):
        _ = metadata
        return {
            "sessionId": session_id or "runtime:test",
            "agentName": agent_name,
            "systemPrompt": system_prompt,
        }


def test_cli_emits_json_for_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agent_cli, "TerraFinAgentClient", _FakeClient)

    exit_code = agent_cli.main(["--transport", "python", "resolve", "AAPL"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"query": "AAPL", "transport": "python"}


def test_cli_returns_nonzero_for_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agent_cli, "TerraFinAgentClient", _FakeClient)

    exit_code = agent_cli.main(["snapshot", "AAPL", "--depth", "full", "--view", "weekly"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.strip() == "boom:AAPL:full:weekly"


def test_cli_supports_runtime_create_session(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agent_cli, "TerraFinAgentClient", _FakeClient)

    exit_code = agent_cli.main(
        [
            "runtime-create-session",
            DEFAULT_HOSTED_AGENT_NAME,
            "--session-id",
            "runtime:cli",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {
        "sessionId": "runtime:cli",
        "agentName": DEFAULT_HOSTED_AGENT_NAME,
        "systemPrompt": None,
    }


def test_cli_models_list_all_reports_featured_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))
    # Block .env autoload + drop the var so a developer's local
    # TERRAFIN_OPENAI_MODEL doesn't leak into the registry-default assertion.
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")
    monkeypatch.delenv("TERRAFIN_OPENAI_MODEL", raising=False)

    payload = agent_cli._models_list_payload(include_models=True)
    assert payload["current"]["modelRef"] == "openai/gpt-4.1-mini"
    assert any(provider["providerId"] == "google" for provider in payload["providers"])
    assert any(
        model["modelRef"] == "google/gemini-3.1-pro-preview"
        for provider in payload["providers"]
        if provider["providerId"] == "google"
        for model in provider["models"]
    )


def test_cli_models_list_all_human_output_is_table(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))
    monkeypatch.setenv("TERRAFIN_DISABLE_DOTENV", "1")
    monkeypatch.delenv("TERRAFIN_OPENAI_MODEL", raising=False)

    exit_code = agent_cli.main(["models", "list", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("Current: openai/gpt-4.1-mini")
    assert "Model" in captured.out
    assert "Auth" in captured.out
    assert "Local" in captured.out
    assert "openai/gpt-4.1-mini" in captured.out
    assert "google/gemini-3.1-pro-preview" in captured.out
    assert not captured.out.lstrip().startswith("{")


def test_cli_models_use_persists_default_model(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(["models", "use", "google/gemini-3.1-pro-preview"])

    captured = capsys.readouterr()
    saved = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Saved default model: google/gemini-3.1-pro-preview" in captured.out
    assert saved["defaultModelRef"] == "google/gemini-3.1-pro-preview"


def test_cli_models_auth_login_saves_token_and_default(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(
        [
            "models",
            "auth",
            "login",
            "--provider",
            "google",
            "--token",
            "AIza_saved_token",
            "--set-default",
            "--yes",
        ]
    )

    captured = capsys.readouterr()
    saved = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Saved Google AI Studio credentials (token)." in captured.out
    assert "Default model: google/gemini-3.1-pro-preview" in captured.out
    assert saved["auth"]["google"]["authMode"] == "token"
    assert saved["auth"]["google"]["apiKey"] == "AIza_saved_token"
    assert saved["defaultModelRef"] == "google/gemini-3.1-pro-preview"


def test_cli_models_auth_login_rejects_device_method(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(["models", "auth", "login", "--provider", "google", "--method", "device", "--yes"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not support device login" in captured.err
