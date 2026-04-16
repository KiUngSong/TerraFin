from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Mapping


MessageRole = Literal["system", "user", "assistant", "tool"]
MessageBlockKind = Literal["text", "tool_use", "tool_result"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TerraFinMessageBlock:
    kind: MessageBlockKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinConversationMessage:
    role: MessageRole
    content: str
    created_at: datetime = field(default_factory=utc_now)
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: tuple[TerraFinMessageBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class TerraFinToolCall:
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinModelTurn:
    assistant_message: TerraFinConversationMessage | None = None
    tool_calls: tuple[TerraFinToolCall, ...] = ()
    stop_reason: Literal["completed", "tool_calls", "max_steps"] = "completed"


@dataclass
class TerraFinHostedConversation:
    session_id: str
    agent_name: str
    messages: list[TerraFinConversationMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> tuple[TerraFinConversationMessage, ...]:
        return tuple(self.messages)


@dataclass(frozen=True, slots=True)
class TerraFinHostedRunResult:
    session_id: str
    agent_name: str
    final_message: TerraFinConversationMessage | None
    messages_added: tuple[TerraFinConversationMessage, ...]
    tool_results: tuple[Any, ...]
    steps: int


def make_text_block(text: str) -> TerraFinMessageBlock:
    return TerraFinMessageBlock(kind="text", payload={"text": str(text or "")})


def make_tool_use_block(
    *,
    call_id: str,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> TerraFinMessageBlock:
    return TerraFinMessageBlock(
        kind="tool_use",
        payload={
            "callId": str(call_id or ""),
            "toolName": str(tool_name or ""),
            "arguments": dict(arguments or {}),
        },
    )


def make_tool_result_block(
    *,
    call_id: str,
    tool_name: str,
    capability_name: str,
    execution_mode: str,
    payload: Mapping[str, Any] | None,
    task: Mapping[str, Any] | None = None,
    is_error: bool = False,
    retryable: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
) -> TerraFinMessageBlock:
    block_payload: dict[str, Any] = {
        "callId": str(call_id or ""),
        "toolName": str(tool_name or ""),
        "capabilityName": str(capability_name or ""),
        "executionMode": str(execution_mode or ""),
        "payload": dict(payload or {}),
        "task": None if task is None else dict(task),
        "isError": bool(is_error),
        "retryable": bool(retryable),
        "errorCode": None if error_code is None else str(error_code),
        "errorMessage": None if error_message is None else str(error_message),
    }
    return TerraFinMessageBlock(kind="tool_result", payload=block_payload)


def serialize_message_blocks(blocks: tuple[TerraFinMessageBlock, ...]) -> list[dict[str, Any]]:
    return [{"kind": block.kind, "payload": dict(block.payload)} for block in blocks]


def deserialize_message_blocks(raw_blocks: Any) -> tuple[TerraFinMessageBlock, ...]:
    if not isinstance(raw_blocks, list):
        return ()
    blocks: list[TerraFinMessageBlock] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, Mapping):
            continue
        kind = str(raw_block.get("kind") or "").strip()
        if kind not in {"text", "tool_use", "tool_result"}:
            continue
        payload = raw_block.get("payload", {})
        blocks.append(TerraFinMessageBlock(kind=kind, payload=dict(payload if isinstance(payload, Mapping) else {})))
    return tuple(blocks)


def is_internal_only_message(message: TerraFinConversationMessage) -> bool:
    return bool(message.metadata.get("internalOnly"))


def iter_tool_use_blocks(message: TerraFinConversationMessage) -> tuple[TerraFinMessageBlock, ...]:
    return tuple(block for block in message.blocks if block.kind == "tool_use")


def iter_tool_result_blocks(message: TerraFinConversationMessage) -> tuple[TerraFinMessageBlock, ...]:
    return tuple(block for block in message.blocks if block.kind == "tool_result")


def infer_message_blocks(message: TerraFinConversationMessage) -> tuple[TerraFinMessageBlock, ...]:
    if message.blocks:
        return tuple(message.blocks)
    if message.role == "tool":
        raw_payload: Any
        try:
            raw_payload = json.loads(message.content)
        except Exception:
            raw_payload = None
        payload = raw_payload if isinstance(raw_payload, Mapping) else {}
        task = payload.get("task")
        return (
            make_tool_result_block(
                call_id=message.tool_call_id or "",
                tool_name=str(payload.get("toolName") or message.name or ""),
                capability_name=str(payload.get("capabilityName") or message.name or ""),
                execution_mode=str(payload.get("executionMode") or message.metadata.get("executionMode") or "invoke"),
                payload=payload.get("payload") if isinstance(payload.get("payload"), Mapping) else {"output": message.content},
                task=task if isinstance(task, Mapping) else None,
                is_error=bool(payload.get("isError") or message.metadata.get("isError")),
                retryable=bool(payload.get("retryable") or message.metadata.get("retryable")),
                error_code=_optional_string(payload.get("errorCode") or message.metadata.get("errorCode")),
                error_message=_optional_string(payload.get("errorMessage") or payload.get("error", {}).get("message")),
            ),
        )
    if message.content.strip():
        return (make_text_block(message.content),)
    return ()


def ensure_message_blocks(message: TerraFinConversationMessage) -> TerraFinConversationMessage:
    if message.blocks:
        return message
    return replace(message, blocks=infer_message_blocks(message))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

