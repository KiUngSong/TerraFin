from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from TerraFin.env import resolve_state_dir

from .definitions import build_default_agent_definition_registry
from .hosted_runtime import TerraFinHostedAgentRuntime
from .loop import TerraFinHostedAgentLoop
from .model_runtime import TerraFinModelProviderRegistry, TerraFinProviderRoutedModelClient
from .providers.github_copilot import TerraFinGithubCopilotResponsesProvider
from .providers.google import TerraFinGoogleResponsesProvider
from .providers.openai import TerraFinOpenAIResponsesProvider
from .runtime import build_default_capability_registry
from .service import TerraFinAgentService
from .session_store import SQLiteHostedSessionStore
from .transcript_store import HostedTranscriptStore


_HOSTED_AGENT_LOOP: TerraFinHostedAgentLoop | None = None
_HOSTED_AGENT_LOOP_LOCK = Lock()


def build_hosted_model_provider_registry() -> TerraFinModelProviderRegistry:
    registry = TerraFinModelProviderRegistry()
    registry.register(TerraFinOpenAIResponsesProvider())
    registry.register(TerraFinGoogleResponsesProvider())
    registry.register(TerraFinGithubCopilotResponsesProvider())
    return registry


def build_hosted_agent_loop() -> TerraFinHostedAgentLoop:
    model_registry = build_hosted_model_provider_registry()
    default_model = model_registry.resolve_default_model_ref()
    service = TerraFinAgentService()
    capability_registry = build_default_capability_registry(service)
    session_db_path = Path(
        os.environ.get(
            "TERRAFIN_AGENT_SESSION_DB_PATH",
            str(resolve_state_dir() / "hosted_agent_sessions.sqlite3"),
        )
    )
    transcript_root = Path(
        os.environ.get(
            "TERRAFIN_AGENT_TRANSCRIPT_DIR",
            str(resolve_state_dir() / "agent"),
        )
    )
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=capability_registry,
        agent_registry=build_default_agent_definition_registry(include_gurus=True),
        session_store=SQLiteHostedSessionStore(
            db_path=session_db_path,
            service=service,
            registry=capability_registry,
        ),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
        default_runtime_model=default_model,
        default_require_human_approval_for_side_effects=True,
        default_require_human_approval_for_background_tasks=False,
    )
    model_client = TerraFinProviderRoutedModelClient(
        registry=model_registry,
        default_model=default_model,
    )
    return TerraFinHostedAgentLoop(runtime=runtime, model_client=model_client)


def _sync_hosted_agent_loop_defaults(loop: TerraFinHostedAgentLoop) -> TerraFinHostedAgentLoop:
    registry = getattr(getattr(loop, "model_client", None), "registry", None)
    resolve_default = getattr(registry, "resolve_default_model_ref", None)
    if not callable(resolve_default):
        return loop
    desired_default = resolve_default()
    current_default = getattr(loop.model_client, "default_model", None)
    if current_default is None or current_default.model_ref != desired_default.model_ref:
        loop.model_client.default_model = desired_default
        loop.runtime.default_runtime_model = desired_default
    return loop


def get_hosted_agent_loop() -> TerraFinHostedAgentLoop:
    global _HOSTED_AGENT_LOOP

    if _HOSTED_AGENT_LOOP is not None:
        return _sync_hosted_agent_loop_defaults(_HOSTED_AGENT_LOOP)

    with _HOSTED_AGENT_LOOP_LOCK:
        if _HOSTED_AGENT_LOOP is None:
            _HOSTED_AGENT_LOOP = build_hosted_agent_loop()
        return _sync_hosted_agent_loop_defaults(_HOSTED_AGENT_LOOP)


def reset_hosted_agent_loop() -> None:
    global _HOSTED_AGENT_LOOP
    with _HOSTED_AGENT_LOOP_LOCK:
        if _HOSTED_AGENT_LOOP is not None:
            _HOSTED_AGENT_LOOP.runtime.shutdown()
        _HOSTED_AGENT_LOOP = None
