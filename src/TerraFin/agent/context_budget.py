import json
from dataclasses import replace
from typing import Any, Literal

from .conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinMessageBlock,
    iter_tool_result_blocks,
    make_text_block,
)
from .transcript_normalizer import TranscriptNormalizer


PromptBudgetLevel = Literal["default", "aggressive", "minimal"]

DEFAULT_MODEL_MESSAGE_WINDOW = 28
DEFAULT_AGGRESSIVE_MODEL_MESSAGE_WINDOW = 12
DEFAULT_MINIMAL_MODEL_MESSAGE_WINDOW = 4
DEFAULT_TOOL_MESSAGE_CHAR_BUDGET = 2200
DEFAULT_AGGRESSIVE_TOOL_MESSAGE_CHAR_BUDGET = 900
DEFAULT_MINIMAL_TOOL_MESSAGE_CHAR_BUDGET = 400
DEFAULT_TEXT_MESSAGE_CHAR_BUDGET = 5000
DEFAULT_AGGRESSIVE_TEXT_MESSAGE_CHAR_BUDGET = 1800
DEFAULT_MINIMAL_TEXT_MESSAGE_CHAR_BUDGET = 900
DEFAULT_ESTIMATED_PROMPT_TOKEN_BUDGET = 52000
PROMPT_BUDGET_RETRY_LEVELS: tuple[PromptBudgetLevel, ...] = ("default", "aggressive", "minimal")


def truncate_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)].rstrip()}…"


def is_prompt_budget_error(error: Exception) -> bool:
    message = str(error or "").lower()
    return any(
        marker in message
        for marker in (
            "model_max_prompt_tokens_exceeded",
            "prompt token count",
            "maximum context length",
            "context_length_exceeded",
            "max prompt tokens",
        )
    )


class ContextBudgetManager:
    def __init__(
        self,
        *,
        normalizer: TranscriptNormalizer,
        estimated_prompt_token_budget: int = DEFAULT_ESTIMATED_PROMPT_TOKEN_BUDGET,
    ) -> None:
        self.normalizer = normalizer
        self.estimated_prompt_token_budget = estimated_prompt_token_budget

    def choose_level(self, conversation: TerraFinHostedConversation) -> PromptBudgetLevel:
        for level in PROMPT_BUDGET_RETRY_LEVELS:
            prepared = self.prepare_messages(conversation, level=level)
            if self.estimate_tokens(prepared) <= self.estimated_prompt_token_budget:
                return level
        return "minimal"

    def prepare_messages(
        self,
        conversation: TerraFinHostedConversation,
        *,
        level: PromptBudgetLevel,
    ) -> tuple[TerraFinConversationMessage, ...]:
        messages = list(self.normalizer.normalize_for_model(conversation))
        if not messages:
            return ()

        system_messages = [message for message in messages if message.role == "system"]
        non_system_messages = [message for message in messages if message.role != "system"]
        selected_non_system = non_system_messages[-self._message_window(level) :]
        dropped_count = max(len(non_system_messages) - len(selected_non_system), 0)

        prepared: list[TerraFinConversationMessage] = []
        if system_messages:
            prepared.append(system_messages[0])
        if dropped_count > 0:
            prepared.append(
                TerraFinConversationMessage(
                    role="system",
                    content=(
                        f"Earlier conversation context was compacted ({dropped_count} prior messages omitted) "
                        "to stay within model limits. Use recent turns and call tools again if older details are needed."
                    ),
                    blocks=(
                        make_text_block(
                            f"Earlier conversation context was compacted ({dropped_count} prior messages omitted) "
                            "to stay within model limits. Use recent turns and call tools again if older details are needed."
                        ),
                    ),
                )
            )

        for message in selected_non_system:
            prepared.append(self._compact_message(message, level=level))
        return tuple(prepared)

    def estimate_tokens(self, messages: tuple[TerraFinConversationMessage, ...]) -> int:
        total_chars = 0
        for message in messages:
            payload = {
                "role": message.role,
                "content": message.content,
                "name": message.name,
                "toolCallId": message.tool_call_id,
                "metadata": message.metadata,
                "blocks": [{"kind": block.kind, "payload": block.payload} for block in message.blocks],
            }
            total_chars += len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return max(total_chars // 4, 1)

    def _compact_message(
        self,
        message: TerraFinConversationMessage,
        *,
        level: PromptBudgetLevel,
    ) -> TerraFinConversationMessage:
        if message.role == "tool":
            blocks = tuple(self._compact_tool_blocks(message.blocks, level=level))
            content = self._serialize_tool_content(blocks, fallback=message.content, level=level)
            return replace(message, content=content, blocks=blocks)

        text_limit = self._text_budget(level)
        content = truncate_text(message.content, text_limit)
        if message.blocks:
            blocks = tuple(
                TerraFinMessageBlock(
                    kind=block.kind, payload={"text": truncate_text(str(block.payload.get("text") or ""), text_limit)}
                )
                if block.kind == "text"
                else block
                for block in message.blocks
            )
        else:
            blocks = (make_text_block(content),) if content else ()
        return replace(message, content=content, blocks=blocks)

    def _compact_tool_blocks(
        self,
        blocks: tuple[TerraFinMessageBlock, ...],
        *,
        level: PromptBudgetLevel,
    ) -> list[TerraFinMessageBlock]:
        compacted: list[TerraFinMessageBlock] = []
        for block in blocks:
            if block.kind != "tool_result":
                compacted.append(block)
                continue
            payload = dict(block.payload)
            payload["payload"] = _compact_payload_value(payload.get("payload"), level=level)
            if isinstance(payload.get("task"), dict):
                payload["task"] = _compact_payload_value(payload.get("task"), level=level)
            compacted.append(TerraFinMessageBlock(kind=block.kind, payload=payload))
        return compacted

    def _serialize_tool_content(
        self,
        blocks: tuple[TerraFinMessageBlock, ...],
        *,
        fallback: str,
        level: PromptBudgetLevel,
    ) -> str:
        tool_blocks = iter_tool_result_blocks(
            TerraFinConversationMessage(role="tool", content=fallback, blocks=blocks)
        )
        tool_block = tool_blocks[0] if tool_blocks else None
        if tool_block is None:
            return truncate_text(fallback, self._tool_budget(level))
        serialized = json.dumps(
            {
                "toolName": tool_block.payload.get("toolName"),
                "capabilityName": tool_block.payload.get("capabilityName"),
                "executionMode": tool_block.payload.get("executionMode"),
                "payload": tool_block.payload.get("payload"),
                "task": tool_block.payload.get("task"),
                "isError": tool_block.payload.get("isError"),
                "retryable": tool_block.payload.get("retryable"),
                "errorCode": tool_block.payload.get("errorCode"),
                "errorMessage": tool_block.payload.get("errorMessage"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return truncate_text(serialized, self._tool_budget(level))

    def _message_window(self, level: PromptBudgetLevel) -> int:
        if level == "minimal":
            return DEFAULT_MINIMAL_MODEL_MESSAGE_WINDOW
        if level == "aggressive":
            return DEFAULT_AGGRESSIVE_MODEL_MESSAGE_WINDOW
        return DEFAULT_MODEL_MESSAGE_WINDOW

    def _tool_budget(self, level: PromptBudgetLevel) -> int:
        if level == "minimal":
            return DEFAULT_MINIMAL_TOOL_MESSAGE_CHAR_BUDGET
        if level == "aggressive":
            return DEFAULT_AGGRESSIVE_TOOL_MESSAGE_CHAR_BUDGET
        return DEFAULT_TOOL_MESSAGE_CHAR_BUDGET

    def _text_budget(self, level: PromptBudgetLevel) -> int:
        if level == "minimal":
            return DEFAULT_MINIMAL_TEXT_MESSAGE_CHAR_BUDGET
        if level == "aggressive":
            return DEFAULT_AGGRESSIVE_TEXT_MESSAGE_CHAR_BUDGET
        return DEFAULT_TEXT_MESSAGE_CHAR_BUDGET


def _compact_payload_value(
    value: Any,
    *,
    level: PromptBudgetLevel,
    depth: int = 0,
) -> Any:
    if level == "minimal":
        max_depth = 1
        max_list_preview = 1
        max_dict_keys = 4
        string_limit = 72
    elif level == "aggressive":
        max_depth = 2
        max_list_preview = 2
        max_dict_keys = 6
        string_limit = 120
    else:
        max_depth = 3
        max_list_preview = 4
        max_dict_keys = 10
        string_limit = 280

    if depth > max_depth:
        if isinstance(value, list):
            return {"count": len(value), "summary": "list"}
        if isinstance(value, dict):
            return {"keys": list(value.keys())[:max_dict_keys], "summary": "object"}
        if isinstance(value, str):
            return truncate_text(value, string_limit)
        return value

    if isinstance(value, dict):
        keys = list(value.keys())
        compacted: dict[str, Any] = {}
        for key in keys[:max_dict_keys]:
            compacted[str(key)] = _compact_payload_value(value[key], level=level, depth=depth + 1)
        if len(keys) > max_dict_keys:
            compacted["_truncatedKeys"] = len(keys) - max_dict_keys
        return compacted

    if isinstance(value, list):
        preview = [_compact_payload_value(item, level=level, depth=depth + 1) for item in value[:max_list_preview]]
        if len(value) > max_list_preview:
            return {"count": len(value), "preview": preview, "truncated": True}
        return preview

    if isinstance(value, str):
        return truncate_text(value, string_limit)

    return value
