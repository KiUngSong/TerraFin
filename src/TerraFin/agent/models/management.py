import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from TerraFin.env import resolve_state_dir


MODEL_STATE_PATH_ENV = "TERRAFIN_AGENT_MODELS_PATH"
DEFAULT_MODEL_STATE_FILENAME = "agent-models.json"
DEFAULT_OPENAI_MODEL_REF = "openai/gpt-4.1-mini"


@dataclass(frozen=True, slots=True)
class TerraFinProviderCatalogEntry:
    provider_id: str
    provider_label: str
    description: str
    default_model_ref: str
    featured_model_refs: tuple[str, ...]
    auth_env_vars: tuple[str, ...]
    auth_field: str
    auth_prompt: str
    auth_kind: Literal["api-key", "github-token"]
    supports_custom_model_ids: bool = True
    notes: str = ""


_PROVIDER_CATALOG: dict[str, TerraFinProviderCatalogEntry] = {
    "openai": TerraFinProviderCatalogEntry(
        provider_id="openai",
        provider_label="OpenAI",
        description="Hosted OpenAI Responses models.",
        default_model_ref="openai/gpt-4.1-mini",
        featured_model_refs=(
            "openai/gpt-4.1-mini",
            "openai/gpt-4.1",
            "openai/gpt-4o",
            "openai/gpt-5",
        ),
        auth_env_vars=("OPENAI_API_KEY",),
        auth_field="apiKey",
        auth_prompt="OpenAI API key",
        auth_kind="api-key",
        notes="Env vars still win over saved local credentials.",
    ),
    "google": TerraFinProviderCatalogEntry(
        provider_id="google",
        provider_label="Google AI Studio",
        description="Gemini API-key backed models.",
        default_model_ref="google/gemini-3.1-pro-preview",
        featured_model_refs=(
            "google/gemini-3.1-pro-preview",
            "google/gemini-3.1-flash",
            "google/gemini-2.5-pro-preview",
        ),
        auth_env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        auth_field="apiKey",
        auth_prompt="Gemini / Google AI Studio API key",
        auth_kind="api-key",
        notes="Canonical refs stay in the form provider/model.",
    ),
    "github-copilot": TerraFinProviderCatalogEntry(
        provider_id="github-copilot",
        provider_label="GitHub Copilot",
        description="OpenAI-compatible GitHub Copilot chat models.",
        default_model_ref="github-copilot/gpt-4o",
        featured_model_refs=(
            "github-copilot/gpt-4o",
            "github-copilot/gpt-4.1",
            "github-copilot/gpt-5",
            "github-copilot/o4-mini",
        ),
        auth_env_vars=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
        auth_field="githubToken",
        auth_prompt="GitHub token with GitHub Copilot access",
        auth_kind="github-token",
        notes="TerraFin v1 supports the OpenAI-compatible Copilot model family only.",
    ),
}


def list_provider_catalog() -> tuple[TerraFinProviderCatalogEntry, ...]:
    return tuple(_PROVIDER_CATALOG.values())


def get_provider_catalog(provider_id: str) -> TerraFinProviderCatalogEntry:
    normalized = str(provider_id or "").strip().lower()
    try:
        return _PROVIDER_CATALOG[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown TerraFin model provider: {provider_id!r}") from exc


def resolve_model_state_path(env: Mapping[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    explicit = str(source.get(MODEL_STATE_PATH_ENV, "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return resolve_state_dir(env) / DEFAULT_MODEL_STATE_FILENAME


def _legacy_model_state_paths(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    source = env if env is not None else os.environ
    if str(source.get(MODEL_STATE_PATH_ENV, "") or "").strip():
        return ()
    if str(source.get("TERRAFIN_STATE_DIR", "") or "").strip():
        return ()

    current = resolve_model_state_path(env)
    candidates: list[Path] = []
    repo_root = current.parent.parent if current.name == DEFAULT_MODEL_STATE_FILENAME else None
    if repo_root is not None:
        legacy = repo_root.parent / ".terrafin" / DEFAULT_MODEL_STATE_FILENAME
        if legacy != current:
            candidates.append(legacy)
    return tuple(candidates)


def _load_model_state_from_path(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"TerraFin model state at '{path}' must be a JSON object.")
    state = _empty_model_state()
    state["version"] = int(payload.get("version", 1) or 1)
    default_model_ref = payload.get("defaultModelRef")
    state["defaultModelRef"] = str(default_model_ref).strip() if isinstance(default_model_ref, str) else None
    auth = payload.get("auth", {})
    if isinstance(auth, Mapping):
        state["auth"] = {
            str(provider_id).strip().lower(): dict(provider_payload)
            for provider_id, provider_payload in auth.items()
            if isinstance(provider_payload, Mapping)
        }
    return state


def _migrate_legacy_model_state_if_needed(env: Mapping[str, str] | None = None) -> Path | None:
    target = resolve_model_state_path(env)
    if target.is_file():
        return target
    for legacy_path in _legacy_model_state_paths(env):
        if not legacy_path.is_file():
            continue
        state = _load_model_state_from_path(legacy_path)
        save_model_state(state, env)
        return target
    return None


def _empty_model_state() -> dict[str, Any]:
    return {
        "version": 1,
        "defaultModelRef": None,
        "auth": {},
    }


def _allow_saved_state(env: Mapping[str, str] | None) -> bool:
    return env is None or MODEL_STATE_PATH_ENV in env


def load_model_state(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if not _allow_saved_state(env):
        return _empty_model_state()
    _migrate_legacy_model_state_if_needed(env)
    path = resolve_model_state_path(env)
    if not path.is_file():
        return _empty_model_state()
    try:
        return _load_model_state_from_path(path)
    except Exception as exc:
        raise ValueError(f"Failed to read TerraFin model state from '{path}'.") from exc


def save_model_state(state: Mapping[str, Any], env: Mapping[str, str] | None = None) -> Path:
    path = resolve_model_state_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(state.get("version", 1) or 1),
        "defaultModelRef": state.get("defaultModelRef"),
        "auth": state.get("auth", {}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def get_saved_default_model_ref(env: Mapping[str, str] | None = None) -> str | None:
    state = load_model_state(env)
    model_ref = state.get("defaultModelRef")
    if isinstance(model_ref, str) and model_ref.strip():
        return model_ref.strip()
    return None


def set_saved_default_model_ref(model_ref: str, env: Mapping[str, str] | None = None) -> Path:
    state = load_model_state(env)
    state["defaultModelRef"] = str(model_ref or "").strip() or None
    return save_model_state(state, env)


def get_saved_provider_credentials(provider_id: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    state = load_model_state(env)
    auth = state.get("auth", {})
    if not isinstance(auth, Mapping):
        return {}
    payload = auth.get(str(provider_id or "").strip().lower(), {})
    return dict(payload) if isinstance(payload, Mapping) else {}


def set_saved_provider_credentials(
    provider_id: str,
    credentials: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> Path:
    normalized_provider_id = str(provider_id or "").strip().lower()
    if not normalized_provider_id:
        raise ValueError("provider_id is required.")
    state = load_model_state(env)
    auth = state.setdefault("auth", {})
    if not isinstance(auth, dict):
        auth = {}
        state["auth"] = auth
    auth[normalized_provider_id] = dict(credentials)
    return save_model_state(state, env)


def resolve_provider_secret(provider_id: str, env: Mapping[str, str] | None = None) -> tuple[str | None, str]:
    catalog = get_provider_catalog(provider_id)
    source = env if env is not None else os.environ
    for env_var in catalog.auth_env_vars:
        secret = str(source.get(env_var, "") or "").strip()
        if secret:
            return secret, "env"
    saved = get_saved_provider_credentials(provider_id, env)
    secret = str(saved.get(catalog.auth_field, "") or "").strip()
    if secret:
        return secret, "saved"
    return None, "none"


def resolve_current_model_preference(
    *,
    env: Mapping[str, str] | None = None,
    default_model_ref: str = DEFAULT_OPENAI_MODEL_REF,
) -> dict[str, str]:
    source = env if env is not None else os.environ
    explicit = str(source.get("TERRAFIN_AGENT_MODEL_REF", "") or "").strip()
    if explicit:
        return {"modelRef": explicit, "source": "env"}
    saved = get_saved_default_model_ref(env)
    if saved:
        return {"modelRef": saved, "source": "saved"}
    legacy_model = str(source.get("TERRAFIN_OPENAI_MODEL", "") or "").strip()
    if legacy_model:
        return {"modelRef": f"openai/{legacy_model}", "source": "legacy-env"}
    return {"modelRef": default_model_ref, "source": "builtin-default"}


def mask_secret(secret: str | None) -> str | None:
    value = str(secret or "").strip()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def build_provider_auth_status(provider_id: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    catalog = get_provider_catalog(provider_id)
    source = env if env is not None else os.environ
    env_secret = None
    for env_var in catalog.auth_env_vars:
        candidate = str(source.get(env_var, "") or "").strip()
        if candidate:
            env_secret = candidate
            break
    saved = get_saved_provider_credentials(provider_id, env)
    saved_secret = str(saved.get(catalog.auth_field, "") or "").strip()
    secret, source = resolve_provider_secret(provider_id, env)
    return {
        "providerId": catalog.provider_id,
        "providerLabel": catalog.provider_label,
        "configured": bool(secret),
        "source": source,
        "authKind": catalog.auth_kind,
        "envVars": list(catalog.auth_env_vars),
        "savedStatePath": str(resolve_model_state_path(env)) if _allow_saved_state(env) else None,
        "credentialHint": mask_secret(secret),
        "envConfigured": bool(env_secret),
        "localConfigured": bool(saved_secret),
    }
