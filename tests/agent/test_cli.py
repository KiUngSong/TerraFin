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

    payload = agent_cli._models_list_payload(include_models=True)
    assert payload["current"]["modelRef"] == "openai/gpt-4.1-mini"
    assert any(provider["providerId"] == "github-copilot" for provider in payload["providers"])
    assert any(
        model["modelRef"] == "github-copilot/gpt-4o"
        for provider in payload["providers"]
        if provider["providerId"] == "github-copilot"
        for model in provider["models"]
    )


def test_cli_models_list_all_human_output_is_table(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(["models", "list", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("Current: openai/gpt-4.1-mini")
    assert "Model" in captured.out
    assert "Auth" in captured.out
    assert "Local" in captured.out
    assert "openai/gpt-4.1-mini" in captured.out
    assert "github-copilot/gpt-4o" in captured.out
    assert not captured.out.lstrip().startswith("{")


def test_cli_models_use_persists_default_model(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(["models", "use", "google/gemini-3.1-pro-preview"])

    captured = capsys.readouterr()
    saved = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Saved default model: google/gemini-3.1-pro-preview" in captured.out
    assert saved["defaultModelRef"] == "google/gemini-3.1-pro-preview"


def test_cli_models_auth_login_github_copilot_saves_token_and_default(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))

    exit_code = agent_cli.main(
        [
            "models",
            "auth",
            "login-github-copilot",
            "--token",
            "ghu_saved_token",
            "--set-default",
            "--yes",
        ]
    )

    captured = capsys.readouterr()
    saved = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Saved GitHub Copilot credentials (token)." in captured.out
    assert "Default model: github-copilot/gpt-4o" in captured.out
    assert saved["auth"]["github-copilot"]["authMode"] == "token"
    assert saved["auth"]["github-copilot"]["githubToken"] == "ghu_saved_token"
    assert saved["defaultModelRef"] == "github-copilot/gpt-4o"


def test_cli_models_auth_login_github_copilot_device_flow(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TERRAFIN_AGENT_MODELS_PATH", str(tmp_path / "agent-models.json"))
    monkeypatch.setattr(agent_cli, "request_github_copilot_device_code", lambda: type(
        "DeviceCode",
        (),
        {
            "device_code": "device-code-123",
            "user_code": "ABCD-EFGH",
            "interval_seconds": 5,
            "expires_in_seconds": 900,
            "authorization_url": "https://github.com/login/device?user_code=ABCD-EFGH",
        },
    )())
    monkeypatch.setattr(
        agent_cli,
        "poll_github_copilot_device_access_token",
        lambda *, device_code, interval_seconds, expires_in_seconds: "gho_device_token",
    )
    monkeypatch.setattr(agent_cli.sys.stdin, "isatty", lambda: True)

    exit_code = agent_cli.main(
        [
            "models",
            "auth",
            "login-github-copilot",
            "--set-default",
            "--yes",
        ]
    )

    captured = capsys.readouterr()
    saved = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Saved GitHub Copilot credentials (device)." in captured.out
    assert "Default model: github-copilot/gpt-4o" in captured.out
    assert "Authorize GitHub Copilot" in captured.err
    assert saved["auth"]["github-copilot"]["authMode"] == "device"
    assert saved["auth"]["github-copilot"]["githubToken"] == "gho_device_token"
