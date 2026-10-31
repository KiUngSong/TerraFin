import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anthropic

from TerraFin.env import ensure_runtime_env_loaded

from ...conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinToolCall,
    iter_tool_result_blocks,
    iter_tool_use_blocks,
)
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


DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
# Streamed, so a large output budget cannot hit the HTTP timeout.
DEFAULT_ANTHROPIC_MAX_TOKENS = 64000
# Set explicitly: claude-opus-5-5 defaults to "medium".
DEFAULT_ANTHROPIC_EFFORT = "high"
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS = 600.0
DEFAULT_ANTHROPIC_MAX_RETRIES = 2
_ANTHROPIC_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
# Models that take adaptive thinking and `effort`, both of which every request sends.
_SUPPORTED_MODELS = frozenset(
    {
        "claude-fable-5-1",
        "claude-fable-5",
        "claude-mythos-5-1",
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-5-5",
    }
)
_FALSE_VALUES = frozenset({"0", "false", "off", "no"})
# Tool-use ids must match ^[a-zA-Z0-9_-]+$; ids minted by other providers may not.
_INVALID_TOOL_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")

# Refusal fallbacks: on a policy decline the API re-runs the same request on the
# model Anthropic recommends for that refusal category. On by default; set
# TERRAFIN_ANTHROPIC_REFUSAL_FALLBACKS=0 to turn them off. Only these models
# accept the "default" form.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})

# A replayed thinking block is valid only while everything before it is unchanged.
# The hosted loop windows, truncates and re-injects earlier messages, so a block it
# invalidates is dropped by the API instead of failing the request.
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"

# Key under which a tool-calling turn's content blocks travel, verbatim, to the next
# request, on its first tool call's provider_data. A turn without tool calls is
# sent back as its text, so nothing it carries reaches message metadata.
ANTHROPIC_CONTENT_KEY = "anthropicContent"

_COMPLETED_STOP_REASONS = frozenset({"end_turn", "stop_sequence", "tool_use"})
_LENGTH_STOP_REASONS = frozenset({"max_tokens", "model_context_window_exceeded"})


class TerraFinAnthropicModelConfigError(TerraFinModelConfigError):
    """Raised when hosted Claude runtime configuration is missing or invalid."""


class TerraFinAnthropicModelResponseError(TerraFinModelResponseError):
    """Raised when the Claude API returns an invalid or failed response."""


@dataclass(frozen=True, slots=True)
class TerraFinAnthropicModelConfig:
    api_key: str
    effort: str = DEFAULT_ANTHROPIC_EFFORT
    refusal_fallbacks: bool = True
    timeout_seconds: float = DEFAULT_ANTHROPIC_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_ANTHROPIC_MAX_RETRIES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TerraFinAnthropicModelConfig":
        if env is None:
            ensure_runtime_env_loaded()
        source = env if env is not None else os.environ
        api_key, _ = resolve_provider_secret("anthropic", env)
        api_key = str(api_key or "").strip()
        if not api_key:
            raise TerraFinAnthropicModelConfigError(
                "ANTHROPIC_API_KEY is required for the hosted Claude agent runtime."
            )
        effort = source.get("TERRAFIN_ANTHROPIC_EFFORT", "").strip().lower() or DEFAULT_ANTHROPIC_EFFORT
        if effort not in _ANTHROPIC_EFFORTS:
            raise TerraFinAnthropicModelConfigError(
                f"TERRAFIN_ANTHROPIC_EFFORT must be one of {', '.join(sorted(_ANTHROPIC_EFFORTS))}."
            )
        fallbacks_raw = source.get("TERRAFIN_ANTHROPIC_REFUSAL_FALLBACKS", "").strip().lower()
        return cls(
            api_key=api_key,
            effort=effort,
            refusal_fallbacks=fallbacks_raw not in _FALSE_VALUES,
            timeout_seconds=_env_float(
                source, "TERRAFIN_ANTHROPIC_TIMEOUT_SECONDS", DEFAULT_ANTHROPIC_TIMEOUT_SECONDS
            ),
            max_retries=_env_int(source, "TERRAFIN_ANTHROPIC_MAX_RETRIES", DEFAULT_ANTHROPIC_MAX_RETRIES, minimum=0),
        )


def _env_int(source: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = source.get(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise TerraFinAnthropicModelConfigError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise TerraFinAnthropicModelConfigError(f"{name} must be at least {minimum}.")
    return value


def _env_float(source: Mapping[str, str], name: str, default: float) -> float:
    raw = source.get(name, "").strip() or str(default)
    try:
        return float(raw)
    except ValueError as exc:
        raise TerraFinAnthropicModelConfigError(f"{name} must be numeric.") from exc


class TerraFinAnthropicMessagesProvider(TerraFinModelProvider):
    provider_id = "anthropic"
    label = "Anthropic"

    def __init__(
        self,
        *,
        config: TerraFinAnthropicModelConfig | None = None,
        env: Mapping[str, str] | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._client = client

    @property
    def config(self) -> TerraFinAnthropicModelConfig:
        if self._config is None:
            self._config = TerraFinAnthropicModelConfig.from_env(self._env)
        return self._config

    def _runtime_client(self) -> Any:
        if self._client is None:
            # The SDK retries 408/409/429/5xx and connection errors itself.
            self._client = anthropic.Anthropic(
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=self.config.max_retries,
            )
        return self._client

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise TerraFinAnthropicModelConfigError("Claude model ids must not be empty.")
        if normalized not in _SUPPORTED_MODELS:
            raise TerraFinAnthropicModelConfigError(
                f"Unsupported Claude model id '{normalized}': TerraFin needs a model that takes adaptive thinking "
                f"and effort. Use one of: {', '.join(sorted(_SUPPORTED_MODELS))}."
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
        _ = session, conversation
        request = self._build_request(model_id=model.model_id, agent=agent, messages=messages, tools=tools)
        try:
            with self._runtime_client().beta.messages.stream(**request) as stream:
                response = stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise TerraFinAnthropicModelConfigError(
                f"Claude API rejected the credentials (HTTP {exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise TerraFinAnthropicModelResponseError(
                f"Claude API request failed (HTTP {exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise TerraFinAnthropicModelResponseError(f"Could not reach the Claude API: {exc}") from exc
        return self._parse_response(response)

    def _build_request(
        self,
        *,
        model_id: str,
        agent: TerraFinAgentDefinition,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> dict[str, Any]:
        system_lines = [message.content for message in messages if message.role == "system" and message.content]
        request: dict[str, Any] = {
            "model": model_id,
            "max_tokens": DEFAULT_ANTHROPIC_MAX_TOKENS,
            "messages": self._build_messages(messages),
            # Thinking is always on for current models; adaptive is the only accepted mode.
            "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
            "output_config": {"effort": self.config.effort},
            "betas": [THINKING_BINDING_BETA],
        }
        if system_lines:
            request["system"] = "\n\n".join(
                [
                    *system_lines,
                    f"Stay within the hosted TerraFin agent definition '{agent.name}' and use tools when they improve accuracy.",
                ]
            )
        if tools:
            request["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": dict(tool.input_schema)}
                for tool in tools
            ]
        if self.config.refusal_fallbacks and model_id in REFUSAL_FALLBACK_MODELS:
            request["betas"].append(REFUSAL_FALLBACK_BETA)
            request["fallbacks"] = "default"
        return request

    def _build_messages(self, messages: tuple[TerraFinConversationMessage, ...]) -> list[dict[str, Any]]:
        conversation = [message for message in messages if message.role != "system"]
        api_messages: list[dict[str, Any]] = []
        # Tool-use ids of the latest assistant turn: only these may be answered by a
        # tool_result. Any other result lost its call to the context window.
        open_call_ids: set[str] = set()
        for index, message in enumerate(conversation):
            if message.role == "assistant":
                following = conversation[index + 1] if index + 1 < len(conversation) else None
                if (
                    not iter_tool_use_blocks(message)
                    and following is not None
                    and iter_tool_use_blocks(following)
                    and _replayable_content(following, turn_text=message.content) is not None
                ):
                    # This turn's text is already inside its tool calls' carried content.
                    continue
                previous = conversation[index - 1] if index > 0 else None
                turn_text = (
                    previous.content
                    if previous is not None and previous.role == "assistant" and not iter_tool_use_blocks(previous)
                    else ""
                )
                carried = _replayable_content(message, turn_text=turn_text)
                blocks = [dict(block) for block in carried] if carried is not None else _rebuilt_blocks(message)
                if not blocks:
                    continue
                if not api_messages or api_messages[-1]["role"] != "assistant":
                    open_call_ids = set()
                open_call_ids.update(block["id"] for block in blocks if block.get("type") == "tool_use")
                _append(api_messages, "assistant", blocks)
                continue
            if message.role == "tool":
                _append(api_messages, "user", [self._tool_result_block(message, open_call_ids)])
                continue
            if message.content.strip():
                _append(api_messages, "user", [{"type": "text", "text": message.content}])
        if api_messages and api_messages[0]["role"] != "user":
            api_messages.insert(
                0, {"role": "user", "content": [{"type": "text", "text": "(Earlier conversation omitted.)"}]}
            )
        if not api_messages:
            raise TerraFinAnthropicModelResponseError("No conversation messages to send to the Claude API.")
        return api_messages

    @staticmethod
    def _tool_result_block(message: TerraFinConversationMessage, open_call_ids: set[str]) -> dict[str, Any]:
        result_blocks = iter_tool_result_blocks(message)
        payload = result_blocks[0].payload if result_blocks else {}
        call_id = _tool_id(message.tool_call_id)
        if call_id not in open_call_ids:
            tool_name = str(payload.get("toolName") or message.name or "tool")
            return {"type": "text", "text": f"[tool result: {tool_name}]\n{message.content}"}
        block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id}
        if message.content:
            block["content"] = message.content
        if payload.get("isError") or message.metadata.get("isError"):
            block["is_error"] = True
        return block

    def _parse_response(self, response: Any) -> TerraFinModelTurn:
        stop_reason = response.stop_reason
        # A declined or cut-off turn is never an answer: its text is partial and its
        # tool inputs may be truncated, so it fails rather than reaching the caller.
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise TerraFinAnthropicModelResponseError(
                f"Claude declined to answer (refusal category: {category}). Rephrase the request and try again."
            )
        if stop_reason in _LENGTH_STOP_REASONS:
            raise TerraFinAnthropicModelResponseError(
                f"Claude's reply was cut off before it finished (stop_reason={stop_reason}). "
                "Ask for a shorter answer or start a new chat."
            )
        content = _echo_content(response.content)
        text = _joined_text(content)
        if stop_reason not in _COMPLETED_STOP_REASONS:
            raise TerraFinAnthropicModelResponseError(f"Claude returned an unsupported stop_reason {stop_reason!r}.")
        tool_calls = [
            TerraFinToolCall(call_id=str(block["id"]), tool_name=str(block["name"]), arguments=dict(block["input"]))
            for block in content
            if block["type"] == "tool_use"
        ]
        if not tool_calls and not text:
            raise TerraFinAnthropicModelResponseError(
                f"Claude returned an empty reply (stop_reason={stop_reason}). Please send your message again."
            )
        if tool_calls:
            first = tool_calls[0]
            tool_calls[0] = TerraFinToolCall(
                call_id=first.call_id,
                tool_name=first.tool_name,
                arguments=first.arguments,
                provider_data={ANTHROPIC_CONTENT_KEY: content},
            )
        assistant_message = TerraFinConversationMessage(role="assistant", content=text) if text else None
        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason="tool_calls" if tool_calls else "completed",
        )


def _append(api_messages: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]) -> None:
    """Consecutive same-role entries become one message, so every tool_result of a
    turn lands in a single user message."""
    if api_messages and api_messages[-1]["role"] == role:
        api_messages[-1]["content"].extend(blocks)
        return
    api_messages.append({"role": role, "content": list(blocks)})


def _carried_content(message: TerraFinConversationMessage) -> list[dict[str, Any]] | None:
    for block in iter_tool_use_blocks(message):
        carried = dict(block.payload.get("providerData") or {}).get(ANTHROPIC_CONTENT_KEY)
        if isinstance(carried, list):
            return carried
    return None


def _joined_text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        block["text"].strip() for block in blocks if block.get("type") == "text" and block["text"].strip()
    )


def _rebuilt_blocks(message: TerraFinConversationMessage) -> list[dict[str, Any]]:
    tool_use_blocks = iter_tool_use_blocks(message)
    rebuilt: list[dict[str, Any]] = []
    if not tool_use_blocks and message.content.strip():
        rebuilt.append({"type": "text", "text": message.content})
    for block in tool_use_blocks:
        rebuilt.append(
            {
                "type": "tool_use",
                "id": _tool_id(block.payload.get("callId")),
                "name": str(block.payload.get("toolName") or ""),
                "input": dict(block.payload.get("arguments", {})),
            }
        )
    return rebuilt


def _tool_id(raw: Any) -> str:
    return _INVALID_TOOL_ID_CHARS.sub("_", str(raw or ""))


def _replayable_content(message: TerraFinConversationMessage, *, turn_text: str) -> list[dict[str, Any]] | None:
    """The carried content blocks, when they can be replayed verbatim.

    Only when the carried turn calls exactly the tools whose results follow it, and
    its text equals `turn_text`, the turn's text as the transcript now holds it. A
    compacted or dropped text means the turn is rebuilt from the transcript instead.
    """
    carried = _carried_content(message)
    if carried is None:
        return None
    carried_ids = {block.get("id") for block in carried if block.get("type") == "tool_use"}
    rebuilt_ids = {block["id"] for block in _rebuilt_blocks(message) if block["type"] == "tool_use"}
    if carried_ids != rebuilt_ids or _joined_text(carried) != turn_text:
        return None
    return carried


def _echo_content(blocks: Any) -> list[dict[str, Any]]:
    """The response's content blocks as they must be sent back next request.

    Before the last fallback boundary only text survives: the declined model's
    thinking and tool calls are not part of the turn. The boundary marker itself
    is dropped.
    """
    serialized = [block.to_dict(mode="json") for block in blocks]
    boundary = max((index for index, block in enumerate(serialized) if block.get("type") == "fallback"), default=-1)
    return [
        block
        for index, block in enumerate(serialized)
        if block.get("type") != "fallback" and (index > boundary or block.get("type") == "text")
    ]


__all__ = [
    "ANTHROPIC_CONTENT_KEY",
    "DEFAULT_ANTHROPIC_MODEL",
    "REFUSAL_FALLBACK_BETA",
    "THINKING_BINDING_BETA",
    "TerraFinAnthropicMessagesProvider",
    "TerraFinAnthropicModelConfig",
    "TerraFinAnthropicModelConfigError",
    "TerraFinAnthropicModelResponseError",
]
