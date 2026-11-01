import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal

from ..contracts.conversation import (
    TOKEN_USAGE_METADATA_KEY,
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinMessageBlock,
    is_internal_only_message,
    iter_tool_result_blocks,
    iter_tool_use_blocks,
    make_text_block,
)
from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY
from .transcript_normalizer import TranscriptNormalizer


PromptBudgetLevel = Literal["full", "default", "aggressive", "minimal"]

READ_TOOL_RESULT_TOOL_NAME = "read_tool_result"

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
# Room kept free of a known context window for the reply and for estimate error.
CONTEXT_WINDOW_RESERVE_FRACTION = 0.15
MIN_CONTEXT_WINDOW_RESERVE_TOKENS = 16000
# "full" sends the whole normalized transcript with no window and no per-message cuts.
PROMPT_BUDGET_RETRY_LEVELS: tuple[PromptBudgetLevel, ...] = ("full", "default", "aggressive", "minimal")


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
            "prompt is too long",
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
        budget = self.prompt_token_budget(conversation)
        # A measured size counts system text and tool definitions too, so it is
        # compared only with a budget taken from the model's real token window.
        use_measured = _context_window(conversation) is not None
        for level in PROMPT_BUDGET_RETRY_LEVELS:
            prepared = self.prepare_messages(conversation, level=level)
            measured = self._measured_estimate(prepared) if use_measured and level == "full" else None
            if (measured if measured is not None else self.estimate_tokens(prepared)) <= budget:
                return level
        return "minimal"

    def prompt_token_budget(self, conversation: TerraFinHostedConversation) -> int:
        window = _context_window(conversation)
        if window is None:
            return self.estimated_prompt_token_budget
        return window - max(int(window * CONTEXT_WINDOW_RESERVE_FRACTION), MIN_CONTEXT_WINDOW_RESERVE_TOKENS)

    def _measured_estimate(self, prepared: tuple[TerraFinConversationMessage, ...]) -> int | None:
        """The provider-measured prompt size up to the latest full-level anchor, plus an
        estimate of every message from the anchor on.

        Only a full-level prompt is append-only, so only its measurement still
        covers the same prefix on a later turn.
        """
        for index in range(len(prepared) - 1, -1, -1):
            usage = prepared[index].metadata.get(TOKEN_USAGE_METADATA_KEY)
            if not isinstance(usage, Mapping) or usage.get("promptLevel") != "full":
                continue
            measured_input = usage.get("input")
            # A provider that reported no prompt count measured nothing.
            if isinstance(measured_input, int) and measured_input > 0:
                return measured_input + self.estimate_tokens(prepared[index:])
        return None

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
        # The current turn, from the latest user-authored message on, is always
        # sent. The level's window is filled from older messages.
        turn_start = _current_turn_start(non_system_messages)
        older = non_system_messages[:turn_start]
        current_turn = non_system_messages[turn_start:]
        current_user = current_turn[0] if current_turn else None
        room = len(older) if level == "full" else max(self._message_window(level) - len(current_turn), 0)
        window_start = len(older) - min(room, len(older))
        # A window never opens on a tool result whose tool_use was cut.
        cut_call_ids = {
            str(block.payload.get("callId") or "")
            for message in older[:window_start]
            for block in iter_tool_use_blocks(message)
        }
        for index in range(window_start, len(older)):
            if older[index].role == "tool" and str(older[index].tool_call_id or "") in cut_call_ids:
                window_start = index + 1
        selected_non_system = older[window_start:] + current_turn
        dropped_count = len(non_system_messages) - len(selected_non_system)

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
            if level == "full" or message is current_user:
                prepared.append(message)
            else:
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
            if message.name == READ_TOOL_RESULT_TOOL_NAME:
                return self._compact_slice(message, level=level)
            note = (
                f"[full result: call_id={message.tool_call_id or ''}, {len(message.content)} chars; "
                "read_tool_result(call_id, offset, limit)]"
            )
            blocks = tuple(self._compact_tool_blocks(message.blocks, level=level))
            payload_cut = blocks != message.blocks
            content = self._serialize_tool_content(
                blocks, fallback=message.content, note=note, payload_cut=payload_cut, level=level
            )
            if payload_cut:
                # A provider that sends the block payload instead of `content` still shows the note.
                blocks = _with_note_in_payload(blocks, note)
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

    def _compact_slice(
        self,
        message: TerraFinConversationMessage,
        *,
        level: PromptBudgetLevel,
    ) -> TerraFinConversationMessage:
        """A slice the model asked for reaches it whole above minimal: its `limit`
        bounds it, and a pointer to it would point back at itself. At minimal it is
        cut like any tool result, so the last level still shrinks the prompt."""
        budget = self._tool_budget(level)
        if level != "minimal" or len(message.content) <= budget:
            return message
        note = "[slice cut to fit the prompt; call read_tool_result again with a smaller limit]"
        content = _cut_with_note(message.content, budget, note=note, cut=True)
        blocks = _with_note_in_payload(tuple(self._compact_tool_blocks(message.blocks, level=level)), note)
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
        note: str,
        payload_cut: bool,
        level: PromptBudgetLevel,
    ) -> str:
        tool_blocks = iter_tool_result_blocks(
            TerraFinConversationMessage(role="tool", content=fallback, blocks=blocks)
        )
        tool_block = tool_blocks[0] if tool_blocks else None
        if tool_block is None:
            return _cut_with_note(fallback, self._tool_budget(level), note=note, cut=False)
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
        return _cut_with_note(serialized, self._tool_budget(level), note=note, cut=payload_cut)

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


def _context_window(conversation: TerraFinHostedConversation) -> int | None:
    runtime_model = conversation.metadata.get(RUNTIME_MODEL_METADATA_KEY)
    model_metadata = runtime_model.get("metadata") if isinstance(runtime_model, Mapping) else None
    window = model_metadata.get("context_window") if isinstance(model_metadata, Mapping) else None
    return window if isinstance(window, int) and window > 0 else None


def _cut_with_note(text: str, limit: int, *, note: str, cut: bool) -> str:
    """`text` within `limit` chars. A cut result keeps its head and tail and ends
    with `note`, which says how to read the rest."""
    if not cut and len(text) <= limit:
        return text
    room = limit - len(note) - 1
    if len(text) <= room:
        return f"{text}\n{note}"
    head = room * 2 // 3
    tail = room - head - 1
    return f"{text[:head]}…{text[len(text) - tail :]}\n{note}"


def _with_note_in_payload(blocks: tuple[TerraFinMessageBlock, ...], note: str) -> tuple[TerraFinMessageBlock, ...]:
    return tuple(
        TerraFinMessageBlock(
            kind=block.kind, payload={**block.payload, "payload": {**block.payload["payload"], "_fullResult": note}}
        )
        if block.kind == "tool_result" and isinstance(block.payload.get("payload"), dict)
        else block
        for block in blocks
    )


def _current_turn_start(messages: list[TerraFinConversationMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user" and not is_internal_only_message(messages[index]):
            return index
    return len(messages)


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
