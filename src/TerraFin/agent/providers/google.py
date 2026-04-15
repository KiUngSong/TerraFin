from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from TerraFin.env import ensure_runtime_env_loaded

from ..conversation_state import get_tool_call_record
from ..definitions import TerraFinAgentDefinition
from ..loop import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinToolCall,
)
from ..model_management import resolve_provider_secret
from ..model_runtime import TerraFinModelConfigError, TerraFinModelProvider, TerraFinModelResponseError, TerraFinRuntimeModel
from ..runtime import TerraFinAgentSession
from ..tools import TerraFinToolDefinition


DEFAULT_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GOOGLE_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GOOGLE_TIMEOUT_SECONDS = 60.0
DEFAULT_GOOGLE_MAX_RETRIES = 2
_GOOGLE_MODEL_RE = re.compile(r"^(gemini|gemma)-[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)


class TerraFinGoogleModelConfigError(TerraFinModelConfigError):
    """Raised when hosted Gemini runtime configuration is missing or invalid."""


class TerraFinGoogleModelResponseError(TerraFinModelResponseError):
    """Raised when the Gemini API returns an invalid or failed payload."""


@dataclass(frozen=True, slots=True)
class TerraFinGoogleModelConfig:
    api_key: str
    base_url: str = DEFAULT_GOOGLE_BASE_URL
    timeout_seconds: float = DEFAULT_GOOGLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_GOOGLE_MAX_RETRIES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TerraFinGoogleModelConfig":
        if env is None:
            ensure_runtime_env_loaded()
        source = env if env is not None else os.environ
        api_key, _ = resolve_provider_secret("google", env)
        api_key = str(api_key or "").strip()
        if not api_key:
            raise TerraFinGoogleModelConfigError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required for the hosted Gemini agent runtime."
            )
        base_url = source.get("TERRAFIN_GOOGLE_BASE_URL", "").strip() or DEFAULT_GOOGLE_BASE_URL
        timeout_raw = source.get("TERRAFIN_GOOGLE_TIMEOUT_SECONDS", "").strip() or str(DEFAULT_GOOGLE_TIMEOUT_SECONDS)
        retry_raw = source.get("TERRAFIN_GOOGLE_MAX_RETRIES", "").strip() or str(DEFAULT_GOOGLE_MAX_RETRIES)
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise TerraFinGoogleModelConfigError("TERRAFIN_GOOGLE_TIMEOUT_SECONDS must be numeric.") from exc
        try:
            max_retries = int(retry_raw)
        except ValueError as exc:
            raise TerraFinGoogleModelConfigError("TERRAFIN_GOOGLE_MAX_RETRIES must be an integer.") from exc
        if max_retries < 0:
            raise TerraFinGoogleModelConfigError("TERRAFIN_GOOGLE_MAX_RETRIES cannot be negative.")
        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )


class TerraFinGoogleResponsesProvider(TerraFinModelProvider):
    provider_id = "google"
    label = "Google AI Studio"

    def __init__(
        self,
        *,
        config: TerraFinGoogleModelConfig | None = None,
        env: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._session = session or requests.Session()

    @property
    def config(self) -> TerraFinGoogleModelConfig:
        if self._config is None:
            self._config = TerraFinGoogleModelConfig.from_env(self._env)
        return self._config

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise TerraFinGoogleModelConfigError("Gemini model ids must not be empty.")
        if not _GOOGLE_MODEL_RE.match(normalized):
            raise TerraFinGoogleModelConfigError(
                f"Unsupported Gemini model id '{normalized}'. Use canonical refs like 'google/gemini-3.1-pro-preview'."
            )
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
        _ = session
        payload = self._build_request_payload(
            agent=agent,
            conversation=conversation,
            messages=messages,
            tools=tools,
        )
        url = f"{self.config.base_url}/models/{model.model_id}:generateContent"
        headers = {
            "x-goog-api-key": self.config.api_key,
            "Content-Type": "application/json",
        }
        response = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempt >= self.config.max_retries:
                    raise TerraFinGoogleModelResponseError(str(exc)) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    break
                continue
            break

        if response is None:
            raise TerraFinGoogleModelResponseError("Gemini API did not return a response.")
        if response.status_code >= 400:
            raise TerraFinGoogleModelResponseError(self._error_message(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise TerraFinGoogleModelResponseError("Gemini API returned a non-JSON response.") from exc
        return self._parse_response(data)

    def _build_request_payload(
        self,
        *,
        agent: TerraFinAgentDefinition,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> dict[str, Any]:
        system_lines = [message.content for message in messages if message.role == "system" and message.content]
        contents: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "user":
                contents.append({"role": "user", "parts": [{"text": message.content}]})
                continue
            if message.role == "assistant":
                if message.content.strip():
                    contents.append({"role": "model", "parts": [{"text": message.content}]})
                continue
            if message.role == "tool":
                call_record = get_tool_call_record(conversation, message.tool_call_id or "")
                if call_record is not None:
                    contents.append(
                        {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": str(call_record.get("toolName") or message.name or ""),
                                        "args": dict(call_record.get("arguments", {})),
                                    }
                                }
                            ],
                        }
                    )
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": message.name or str(call_record.get("toolName") if call_record else ""),
                                    "response": self._parse_tool_output(message.content),
                                }
                            }
                        ],
                    }
                )

        payload: dict[str, Any] = {
            "contents": contents,
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": dict(tool.input_schema),
                        }
                        for tool in tools
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "AUTO",
                }
            },
        }
        if system_lines:
            payload["systemInstruction"] = {
                "parts": [
                    {
                        "text": "\n\n".join(
                            [
                                *system_lines,
                                f"Stay within the hosted TerraFin agent definition '{agent.name}' and use tools when they improve accuracy.",
                            ]
                        )
                    }
                ]
            }
        return payload

    def _parse_tool_output(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {"output": content}
        return parsed if isinstance(parsed, dict) else {"output": parsed}

    def _parse_response(self, payload: Mapping[str, Any]) -> TerraFinModelTurn:
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list) or not candidates:
            prompt_feedback = payload.get("promptFeedback")
            if isinstance(prompt_feedback, Mapping):
                block_reason = prompt_feedback.get("blockReason")
                if block_reason:
                    raise TerraFinGoogleModelResponseError(f"Gemini blocked the request: {block_reason}")
            raise TerraFinGoogleModelResponseError("Gemini returned no candidates.")
        first = candidates[0]
        if not isinstance(first, Mapping):
            raise TerraFinGoogleModelResponseError("Gemini returned an invalid candidate payload.")
        content = first.get("content", {})
        if not isinstance(content, Mapping):
            raise TerraFinGoogleModelResponseError("Gemini returned an invalid content payload.")
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            raise TerraFinGoogleModelResponseError("Gemini returned an invalid content parts payload.")
        texts: list[str] = []
        tool_calls: list[TerraFinToolCall] = []
        for index, part in enumerate(parts):
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            function_call = part.get("functionCall")
            if not isinstance(function_call, Mapping):
                continue
            tool_name = str(function_call.get("name") or "").strip()
            if not tool_name:
                raise TerraFinGoogleModelResponseError("Gemini functionCall was missing a name.")
            arguments = function_call.get("args", {})
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, Mapping):
                raise TerraFinGoogleModelResponseError(
                    f"Gemini functionCall arguments for '{tool_name}' must decode to an object."
                )
            call_id = str(function_call.get("id") or f"gemini-call:{index}:{uuid4().hex}").strip()
            tool_calls.append(
                TerraFinToolCall(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                )
            )
        assistant_message = (
            TerraFinConversationMessage(role="assistant", content="\n".join(texts).strip()) if texts else None
        )
        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason="tool_calls" if tool_calls else "completed",
        )

    def _error_message(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"Gemini API request failed: HTTP {response.status_code}"
        if isinstance(payload, dict):
            error = payload.get("error", {})
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message
        return f"Gemini API request failed: HTTP {response.status_code}"
