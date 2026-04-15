from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from TerraFin.env import ensure_runtime_env_loaded

from ..conversation_state import get_provider_state
from ..definitions import TerraFinAgentDefinition
from ..loop import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinHostedModelClient,
    TerraFinModelTurn,
)
from ..model_runtime import (
    TerraFinModelConfigError,
    TerraFinModelProvider,
    TerraFinModelResponseError,
    TerraFinRuntimeModel,
)
from ..model_management import resolve_provider_secret
from ..runtime import TerraFinAgentSession
from ..tools import TerraFinToolDefinition
from .openai_compatible import OpenAICompatibleResponsesRunner


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_MAX_RETRIES = 2


class TerraFinOpenAIConfigError(TerraFinModelConfigError):
    """Raised when hosted OpenAI runtime configuration is missing or invalid."""


class TerraFinOpenAIResponseError(TerraFinModelResponseError):
    """Raised when the OpenAI Responses API returns an invalid or failed payload."""


@dataclass(frozen=True, slots=True)
class TerraFinOpenAIModelConfig:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL
    base_url: str = DEFAULT_OPENAI_BASE_URL
    timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_MAX_RETRIES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TerraFinOpenAIModelConfig":
        if env is None:
            ensure_runtime_env_loaded()
        source = env if env is not None else os.environ
        api_key, _ = resolve_provider_secret("openai", env)
        api_key = str(api_key or "").strip()
        if not api_key:
            raise TerraFinOpenAIConfigError("OPENAI_API_KEY is required for the hosted OpenAI agent runtime.")

        model = source.get("TERRAFIN_OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
        base_url = source.get("TERRAFIN_OPENAI_BASE_URL", "").strip() or DEFAULT_OPENAI_BASE_URL
        timeout_raw = source.get("TERRAFIN_OPENAI_TIMEOUT_SECONDS", "").strip() or str(DEFAULT_OPENAI_TIMEOUT_SECONDS)
        retry_raw = source.get("TERRAFIN_OPENAI_MAX_RETRIES", "").strip() or str(DEFAULT_OPENAI_MAX_RETRIES)
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise TerraFinOpenAIConfigError("TERRAFIN_OPENAI_TIMEOUT_SECONDS must be numeric.") from exc
        try:
            max_retries = int(retry_raw)
        except ValueError as exc:
            raise TerraFinOpenAIConfigError("TERRAFIN_OPENAI_MAX_RETRIES must be an integer.") from exc
        if max_retries < 0:
            raise TerraFinOpenAIConfigError("TERRAFIN_OPENAI_MAX_RETRIES cannot be negative.")
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )


class TerraFinOpenAIResponsesProvider(TerraFinModelProvider):
    provider_id = "openai"
    label = "OpenAI"

    def __init__(
        self,
        *,
        config: TerraFinOpenAIModelConfig | None = None,
        env: Mapping[str, str] | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._client = client

    @property
    def config(self) -> TerraFinOpenAIModelConfig:
        if self._config is None:
            self._config = TerraFinOpenAIModelConfig.from_env(self._env)
        return self._config

    def _runtime_client(self) -> Any:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise TerraFinOpenAIConfigError("OpenAI model ids must not be empty.")
        return TerraFinRuntimeModel(
            model_ref=f"{self.provider_id}/{normalized}",
            provider_id=self.provider_id,
            provider_label=self.label,
            model_id=normalized,
        )

    def complete(
        self,
        *,
        model: TerraFinRuntimeModel,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> TerraFinModelTurn:
        legacy_response_id = str(conversation.metadata.get("openai_response_id") or "").strip() or None
        try:
            legacy_message_cursor = int(conversation.metadata.get("openai_message_cursor", 0))
        except Exception:
            legacy_message_cursor = 0
        runner = OpenAICompatibleResponsesRunner(
            provider_id=self.provider_id,
            max_retries=self.config.max_retries,
            response_error_cls=TerraFinOpenAIResponseError,
        )
        turn = runner.complete(
            client=self._runtime_client(),
            model_id=model.model_id,
            agent=agent,
            session=session,
            conversation=conversation,
            messages=messages,
            tools=tools,
            legacy_response_id=legacy_response_id,
            legacy_message_cursor=legacy_message_cursor,
        )
        provider_state = get_provider_state(conversation, self.provider_id)
        if provider_state:
            conversation.metadata["openai_response_id"] = provider_state.get("responseId")
            conversation.metadata["openai_message_cursor"] = provider_state.get("messageCursor", 0)
        return turn


class TerraFinOpenAIResponsesModelClient(TerraFinHostedModelClient):
    def __init__(
        self,
        *,
        config: TerraFinOpenAIModelConfig | None = None,
        env: Mapping[str, str] | None = None,
        client: Any | None = None,
    ) -> None:
        self.provider = TerraFinOpenAIResponsesProvider(config=config, env=env, client=client)
        self.config = self.provider.config
        self.runtime_model = self.provider.resolve_model(self.config.model)

    def complete(
        self,
        *,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> TerraFinModelTurn:
        return self.provider.complete(
            model=self.runtime_model,
            agent=agent,
            session=session,
            conversation=conversation,
            messages=messages,
            tools=tools,
        )
