from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from TerraFin.env import ensure_runtime_env_loaded

from .conversation_state import RUNTIME_MODEL_METADATA_KEY
from .model_management import DEFAULT_OPENAI_MODEL_REF, get_saved_default_model_ref

if TYPE_CHECKING:
    from .definitions import TerraFinAgentDefinition
    from .loop import TerraFinConversationMessage, TerraFinHostedConversation, TerraFinModelTurn
    from .runtime import TerraFinAgentSession

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class TerraFinModelConfigError(ValueError):
    """Raised when the configured hosted model provider is missing or invalid."""


class TerraFinModelResponseError(RuntimeError):
    """Raised when a hosted model provider returns an invalid or failed payload."""


@dataclass(frozen=True, slots=True)
class TerraFinRuntimeModel:
    model_ref: str
    provider_id: str
    provider_label: str
    model_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "modelRef": self.model_ref,
            "providerId": self.provider_id,
            "providerLabel": self.provider_label,
            "modelId": self.model_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TerraFinRuntimeModel":
        model_ref = str(payload.get("modelRef") or "").strip()
        provider_id = str(payload.get("providerId") or "").strip()
        provider_label = str(payload.get("providerLabel") or "").strip()
        model_id = str(payload.get("modelId") or "").strip()
        if not model_ref or not provider_id or not provider_label or not model_id:
            raise TerraFinModelConfigError("Hosted runtime model payload is missing required fields.")
        return cls(
            model_ref=model_ref,
            provider_id=provider_id,
            provider_label=provider_label,
            model_id=model_id,
            metadata=dict(payload.get("metadata", {})),
        )


class TerraFinModelProvider(Protocol):
    provider_id: str
    label: str

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel: ...

    def complete(
        self,
        *,
        model: TerraFinRuntimeModel,
        agent: "TerraFinAgentDefinition",
        session: "TerraFinAgentSession",
        conversation: "TerraFinHostedConversation",
        messages: tuple["TerraFinConversationMessage", ...],
        tools: tuple[Any, ...],
    ) -> "TerraFinModelTurn": ...


class TerraFinModelProviderRegistry:
    def __init__(self, providers: Mapping[str, TerraFinModelProvider] | None = None) -> None:
        self._providers: dict[str, TerraFinModelProvider] = {}
        for provider in (providers or {}).values():
            self.register(provider)

    def register(self, provider: TerraFinModelProvider) -> TerraFinModelProvider:
        provider_id = str(provider.provider_id or "").strip().lower()
        if not provider_id or not _PROVIDER_ID_RE.match(provider_id):
            raise TerraFinModelConfigError(f"Invalid TerraFin model provider id: {provider.provider_id!r}")
        self._providers[provider_id] = provider
        return provider

    def get(self, provider_id: str) -> TerraFinModelProvider:
        normalized = str(provider_id or "").strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            raise TerraFinModelConfigError(f"Unsupported TerraFin model provider: {provider_id!r}")
        return provider

    def list(self) -> tuple[TerraFinModelProvider, ...]:
        return tuple(self._providers.values())

    def parse_model_ref(self, model_ref: str) -> tuple[str, str]:
        raw = str(model_ref or "").strip()
        provider_id, separator, model_id = raw.partition("/")
        provider_id = provider_id.strip().lower()
        model_id = model_id.strip()
        if (
            not separator
            or not provider_id
            or not model_id
            or not _PROVIDER_ID_RE.match(provider_id)
            or any(char.isspace() for char in model_id)
        ):
            raise TerraFinModelConfigError(
                "Hosted model refs must use the canonical 'provider/model' format."
            )
        return provider_id, model_id

    def resolve_model_ref(self, model_ref: str) -> TerraFinRuntimeModel:
        provider_id, model_id = self.parse_model_ref(model_ref)
        return self.get(provider_id).resolve_model(model_id)

    def coerce_runtime_model(self, payload: Any) -> TerraFinRuntimeModel:
        if isinstance(payload, TerraFinRuntimeModel):
            return payload
        if isinstance(payload, Mapping):
            model_ref = str(payload.get("modelRef") or "").strip()
            if model_ref:
                try:
                    resolved = self.resolve_model_ref(model_ref)
                except TerraFinModelConfigError:
                    return TerraFinRuntimeModel.from_payload(payload)
                metadata = dict(payload.get("metadata", {}))
                return TerraFinRuntimeModel(
                    model_ref=resolved.model_ref,
                    provider_id=resolved.provider_id,
                    provider_label=str(payload.get("providerLabel") or resolved.provider_label),
                    model_id=str(payload.get("modelId") or resolved.model_id),
                    metadata=metadata,
                )
            return TerraFinRuntimeModel.from_payload(payload)
        if isinstance(payload, str):
            return self.resolve_model_ref(payload)
        raise TerraFinModelConfigError("Unsupported hosted runtime model payload.")

    def resolve_default_model_ref(self, env: Mapping[str, str] | None = None) -> TerraFinRuntimeModel:
        if env is None:
            ensure_runtime_env_loaded()
        source = env if env is not None else os.environ
        explicit = str(source.get("TERRAFIN_AGENT_MODEL_REF", "") or "").strip()
        if explicit:
            return self.resolve_model_ref(explicit)
        saved = get_saved_default_model_ref(env)
        if saved:
            return self.resolve_model_ref(saved)
        legacy_model = str(source.get("TERRAFIN_OPENAI_MODEL", "") or "").strip()
        return self.resolve_model_ref(f"openai/{legacy_model or DEFAULT_OPENAI_MODEL_REF.split('/', 1)[1]}")


class TerraFinProviderRoutedModelClient:
    def __init__(
        self,
        *,
        registry: TerraFinModelProviderRegistry,
        default_model: TerraFinRuntimeModel,
    ) -> None:
        self.registry = registry
        self.default_model = default_model

    def describe_runtime_model(self, *, session: "TerraFinAgentSession" | None = None) -> TerraFinRuntimeModel:
        if session is None:
            return self.default_model
        payload = session.metadata.get(RUNTIME_MODEL_METADATA_KEY)
        if payload is None:
            return self.default_model
        return self.registry.coerce_runtime_model(payload)

    def describe_runtime_status(self, *, session: "TerraFinAgentSession" | None = None) -> dict[str, Any]:
        runtime_model = self.describe_runtime_model(session=session)
        provider = self.registry.get(runtime_model.provider_id)
        try:
            getattr(provider, "config")
        except TerraFinModelConfigError as exc:
            return {
                "runtimeModel": runtime_model.to_payload(),
                "configured": False,
                "message": str(exc),
            }
        return {
            "runtimeModel": runtime_model.to_payload(),
            "configured": True,
            "message": None,
        }

    def complete(
        self,
        *,
        agent: "TerraFinAgentDefinition",
        session: "TerraFinAgentSession",
        conversation: "TerraFinHostedConversation",
        messages: tuple["TerraFinConversationMessage", ...],
        tools: tuple[Any, ...],
    ) -> "TerraFinModelTurn":
        runtime_model = self.describe_runtime_model(session=session)
        session.metadata[RUNTIME_MODEL_METADATA_KEY] = runtime_model.to_payload()
        conversation.metadata.setdefault(RUNTIME_MODEL_METADATA_KEY, runtime_model.to_payload())
        provider = self.registry.get(runtime_model.provider_id)
        return provider.complete(
            model=runtime_model,
            agent=agent,
            session=session,
            conversation=conversation,
            messages=messages,
            tools=tools,
        )
