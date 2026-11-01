import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from TerraFin.env import ensure_runtime_env_loaded

from ...contracts.model_client import TerraFinTurnOptions
from ...conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinTokenUsage,
    TerraFinToolCall,
    iter_tool_result_blocks,
    iter_tool_use_blocks,
)
from ...conversation_state import get_tool_call_record
from ...definitions import TerraFinAgentDefinition
from ...runtime.session import TerraFinAgentSession
from ...tools import TerraFinToolDefinition
from ..management import resolve_provider_secret
from ..runtime import (
    TerraFinModelConfigError,
    TerraFinModelProvider,
    TerraFinModelResponseError,
    TerraFinRuntimeModel,
)


DEFAULT_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GOOGLE_MODEL = "gemini-4-argon"
DEFAULT_GOOGLE_TIMEOUT_SECONDS = 60.0
DEFAULT_GOOGLE_MAX_RETRIES = 2
_GOOGLE_MODEL_RE = re.compile(r"^(gemini|gemma)-[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)
_RETRY_BACKOFF_SECONDS = 0.5
_RETRY_BACKOFF_CAP_SECONDS = 8.0
_GOOGLE_STOP_REASONS = {
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
}


def _retry_delay(attempt: int) -> float:
    return min(_RETRY_BACKOFF_SECONDS * 2**attempt, _RETRY_BACKOFF_CAP_SECONDS)


def _usage(metadata: Any) -> TerraFinTokenUsage | None:
    if not isinstance(metadata, Mapping):
        return None
    # promptTokenCount already includes cached content. Thinking is billed as output.
    return TerraFinTokenUsage(
        input=int(metadata.get("promptTokenCount") or 0),
        output=int(metadata.get("candidatesTokenCount") or 0) + int(metadata.get("thoughtsTokenCount") or 0),
        cache_read=int(metadata.get("cachedContentTokenCount") or 0),
    )


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
                f"Unsupported Gemini model id '{normalized}'. Use canonical refs like 'google/gemini-4-argon'."
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
        options: TerraFinTurnOptions | None = None,
    ) -> TerraFinModelTurn:
        _ = session
        payload = self._build_request_payload(
            agent=agent,
            conversation=conversation,
            messages=messages,
            tools=tools,
            options=options or TerraFinTurnOptions(),
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
                time.sleep(_retry_delay(attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    break
                time.sleep(_retry_delay(attempt))
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
        options: TerraFinTurnOptions = TerraFinTurnOptions(),
    ) -> dict[str, Any]:
        system_lines = [message.content for message in messages if message.role == "system" and message.content]
        contents: list[dict[str, Any]] = []
        # Call ids of the latest model turn: only these may be answered by a
        # functionResponse. Any other result lost its call to the context window.
        open_call_ids: set[str] = set()
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "user":
                contents.append({"role": "user", "parts": [{"text": message.content}]})
                continue
            if message.role == "assistant":
                parts: list[dict[str, Any]] = []
                if message.content.strip():
                    parts.append({"text": message.content})
                for block in iter_tool_use_blocks(message):
                    part: dict[str, Any] = {
                        "functionCall": {
                            "name": str(block.payload.get("toolName") or ""),
                            "args": dict(block.payload.get("arguments", {})),
                        }
                    }
                    signature = dict(block.payload.get("providerData") or {}).get("thoughtSignature")
                    if signature:
                        part["thoughtSignature"] = signature
                    parts.append(part)
                if parts:
                    if not contents or contents[-1]["role"] != "model":
                        open_call_ids = set()
                    open_call_ids.update(
                        str(block.payload.get("callId") or "") for block in iter_tool_use_blocks(message)
                    )
                    self._append_turn(contents, "model", parts)
                continue
            if message.role == "tool":
                tool_result_blocks = iter_tool_result_blocks(message)
                tool_result_block = tool_result_blocks[0] if tool_result_blocks else None
                if str(message.tool_call_id or "") not in open_call_ids:
                    result_payload = tool_result_block.payload if tool_result_block is not None else {}
                    tool_name = str(result_payload.get("toolName") or message.name or "tool")
                    text = f"[tool result: {tool_name}]\n{message.content}"
                    contents.append({"role": "user", "parts": [{"text": text}]})
                    continue
                call_record = get_tool_call_record(conversation, message.tool_call_id or "")
                if tool_result_block is not None:
                    tool_name = str(
                        tool_result_block.payload.get("toolName")
                        or message.name
                        or (call_record or {}).get("toolName")
                        or ""
                    )
                    response_payload = dict(tool_result_block.payload.get("payload", {}))
                else:
                    tool_name = message.name or str((call_record or {}).get("toolName") or "")
                    response_payload = self._parse_tool_output(message.content)
                self._append_turn(
                    contents,
                    "user",
                    [
                        {
                            "functionResponse": {
                                "name": tool_name,
                                "response": response_payload,
                            }
                        }
                    ],
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
                    "mode": "NONE" if options.tool_choice == "none" else "AUTO",
                }
            },
        }
        instruction_lines = (
            [
                *system_lines,
                f"Stay within the hosted TerraFin agent definition '{agent.name}' and use tools when they improve accuracy.",
            ]
            if system_lines
            else []
        )
        if options.pinned_context:
            instruction_lines.append(options.pinned_context)
        if instruction_lines:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(instruction_lines)}]}
        return payload

    @staticmethod
    def _append_turn(contents: list[dict[str, Any]], role: str, parts: list[dict[str, Any]]) -> None:
        """Gemini wants one model turn per step, holding its text then every call,
        and one user turn holding every response to those calls."""
        previous = contents[-1] if contents else None
        if (
            previous is not None
            and previous["role"] == role
            and (role == "model" or all("functionResponse" in part for part in [*previous["parts"], *parts]))
        ):
            previous["parts"].extend(parts)
            return
        contents.append({"role": role, "parts": parts})

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
            signature = part.get("thoughtSignature")
            tool_calls.append(
                TerraFinToolCall(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    provider_data={"thoughtSignature": signature} if isinstance(signature, str) and signature else {},
                )
            )
        assistant_message = (
            TerraFinConversationMessage(role="assistant", content="\n".join(texts).strip()) if texts else None
        )
        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason=_GOOGLE_STOP_REASONS.get(
                str(first.get("finishReason") or ""),
                "tool_calls" if tool_calls else "completed",
            ),
            usage=_usage(payload.get("usageMetadata")),
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
