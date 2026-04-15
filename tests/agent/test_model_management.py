import json
from pathlib import Path

from TerraFin.agent.model_management import (
    build_provider_auth_status,
    get_saved_default_model_ref,
    resolve_model_state_path,
    resolve_current_model_preference,
    resolve_provider_secret,
    set_saved_default_model_ref,
    set_saved_provider_credentials,
)
from TerraFin.env import resolve_state_dir


def test_saved_default_model_ref_round_trips_through_model_state(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}

    set_saved_default_model_ref("github-copilot/gpt-4o", env)

    assert get_saved_default_model_ref(env) == "github-copilot/gpt-4o"
    payload = json.loads((tmp_path / "agent-models.json").read_text(encoding="utf-8"))
    assert payload["defaultModelRef"] == "github-copilot/gpt-4o"


def test_shared_state_dir_defaults_to_repo_scoped_terrafin_dir() -> None:
    expected = Path(__file__).resolve().parents[2] / ".terrafin"

    assert resolve_state_dir({}) == expected


def test_model_state_path_uses_shared_state_dir_when_file_path_not_overridden(tmp_path) -> None:
    env = {"TERRAFIN_STATE_DIR": str(tmp_path / "state")}

    assert resolve_model_state_path(env) == tmp_path / "state" / "agent-models.json"


def test_resolve_current_model_preference_uses_saved_default_when_env_missing(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_default_model_ref("google/gemini-3.1-pro-preview", env)

    current = resolve_current_model_preference(env=env)

    assert current == {"modelRef": "google/gemini-3.1-pro-preview", "source": "saved"}


def test_provider_secret_prefers_env_over_saved_state(tmp_path) -> None:
    env = {
        "TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json"),
        "OPENAI_API_KEY": "env-openai-key",
    }
    set_saved_provider_credentials("openai", {"apiKey": "saved-openai-key"}, env)

    secret, source = resolve_provider_secret("openai", env)

    assert secret == "env-openai-key"
    assert source == "env"


def test_provider_auth_status_reports_saved_credentials(tmp_path) -> None:
    env = {"TERRAFIN_AGENT_MODELS_PATH": str(tmp_path / "agent-models.json")}
    set_saved_provider_credentials("github-copilot", {"githubToken": "ghu_saved_token"}, env)

    status = build_provider_auth_status("github-copilot", env)

    assert status["configured"] is True
    assert status["source"] == "saved"
    assert status["credentialHint"] == "ghu_...oken"
