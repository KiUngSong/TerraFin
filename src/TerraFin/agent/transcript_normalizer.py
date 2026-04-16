from __future__ import annotations

from dataclasses import replace

from .conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    ensure_message_blocks,
    iter_tool_result_blocks,
    iter_tool_use_blocks,
    make_tool_use_block,
)
from .conversation_state import TOOL_CALL_HISTORY_METADATA_KEY, get_tool_call_record


class TranscriptNormalizer:
    def normalize_loaded_conversation(
        self,
        conversation: TerraFinHostedConversation,
    ) -> TerraFinHostedConversation:
        messages = self._normalize_messages(conversation, for_model=False)
        conversation.messages = list(messages)
        conversation.metadata[TOOL_CALL_HISTORY_METADATA_KEY] = self._tool_call_history(messages)
        return conversation

    def normalize_for_model(
        self,
        conversation: TerraFinHostedConversation,
    ) -> tuple[TerraFinConversationMessage, ...]:
        return self._normalize_messages(conversation, for_model=True)

    def _normalize_messages(
        self,
        conversation: TerraFinHostedConversation,
        *,
        for_model: bool,
    ) -> tuple[TerraFinConversationMessage, ...]:
        source = [ensure_message_blocks(message) for message in conversation.snapshot()]
        result_call_ids = {
            str(block.payload.get("callId") or "").strip()
            for message in source
            for block in iter_tool_result_blocks(message)
            if str(block.payload.get("callId") or "").strip()
        }

        normalized: list[TerraFinConversationMessage] = []
        seen_call_ids: set[str] = set()
        for message in source:
            tool_use_blocks = iter_tool_use_blocks(message)
            if tool_use_blocks:
                paired_blocks = (
                    tuple(
                        block
                        for block in tool_use_blocks
                        if str(block.payload.get("callId") or "").strip() in result_call_ids
                    )
                    if for_model
                    else tool_use_blocks
                )
                if not paired_blocks:
                    continue
                normalized_message = replace(message, blocks=paired_blocks)
                normalized.append(normalized_message)
                for block in paired_blocks:
                    seen_call_ids.add(str(block.payload.get("callId") or "").strip())
                continue

            if message.role == "tool":
                call_id = str(message.tool_call_id or "").strip()
                if not call_id:
                    continue
                if call_id not in seen_call_ids:
                    record = get_tool_call_record(conversation, call_id)
                    tool_result_blocks = iter_tool_result_blocks(message)
                    tool_name = (
                        str(tool_result_blocks[0].payload.get("toolName") or "").strip()
                        if tool_result_blocks
                        else str(message.name or "").strip()
                    )
                    arguments = {}
                    if record is not None:
                        tool_name = str(record.get("toolName") or tool_name or "").strip()
                        arguments = dict(record.get("arguments", {}))
                    if not tool_name:
                        continue
                    synthetic_tool_use = TerraFinConversationMessage(
                        role="assistant",
                        content="",
                        metadata={"internalOnly": True, "internalToolUse": True},
                        blocks=(
                            make_tool_use_block(
                                call_id=call_id,
                                tool_name=tool_name,
                                arguments=arguments,
                            ),
                        ),
                    )
                    normalized.append(synthetic_tool_use)
                    seen_call_ids.add(call_id)
                normalized.append(message)
                continue

            if message.role == "assistant" and not message.content.strip():
                continue
            normalized.append(message)
        return tuple(normalized)

    def _tool_call_history(
        self,
        messages: tuple[TerraFinConversationMessage, ...],
    ) -> list[dict[str, object]]:
        history: list[dict[str, object]] = []
        seen: set[str] = set()
        for message in messages:
            for block in iter_tool_use_blocks(message):
                call_id = str(block.payload.get("callId") or "").strip()
                tool_name = str(block.payload.get("toolName") or "").strip()
                if not call_id or not tool_name or call_id in seen:
                    continue
                history.append(
                    {
                        "callId": call_id,
                        "toolName": tool_name,
                        "arguments": dict(block.payload.get("arguments", {})),
                    }
                )
                seen.add(call_id)
        return history
