from collections.abc import Iterable
from typing import Any


PROVIDER_STATE_METADATA_KEY = "providerState"
RUNTIME_MODEL_METADATA_KEY = "runtimeModel"
TOOL_CALL_HISTORY_METADATA_KEY = "toolCallHistory"


def get_provider_state(conversation: Any, provider_id: str) -> dict[str, Any]:
    provider_state = conversation.metadata.get(PROVIDER_STATE_METADATA_KEY, {})
    if not isinstance(provider_state, dict):
        return {}
    state = provider_state.get(provider_id, {})
    return dict(state) if isinstance(state, dict) else {}


def set_provider_state(conversation: Any, provider_id: str, state: dict[str, Any]) -> dict[str, Any]:
    provider_state = conversation.metadata.get(PROVIDER_STATE_METADATA_KEY)
    if not isinstance(provider_state, dict):
        provider_state = {}
    provider_state[provider_id] = dict(state)
    conversation.metadata[PROVIDER_STATE_METADATA_KEY] = provider_state
    return dict(provider_state[provider_id])


def iter_tool_call_history(conversation: Any) -> tuple[dict[str, Any], ...]:
    history = conversation.metadata.get(TOOL_CALL_HISTORY_METADATA_KEY, ())
    if not isinstance(history, list):
        return ()
    items: list[dict[str, Any]] = []
    for item in history:
        if isinstance(item, dict):
            items.append(dict(item))
    return tuple(items)


def get_tool_call_record(conversation: Any, call_id: str) -> dict[str, Any] | None:
    normalized_call_id = str(call_id or "").strip()
    if not normalized_call_id:
        return None
    for item in iter_tool_call_history(conversation):
        if str(item.get("callId") or "").strip() == normalized_call_id:
            return item
    return None


def record_tool_call_history(conversation: Any, tool_calls: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    history = list(iter_tool_call_history(conversation))
    for tool_call in tool_calls:
        call_id = str(getattr(tool_call, "call_id", "") or "").strip()
        tool_name = str(getattr(tool_call, "tool_name", "") or "").strip()
        if not call_id or not tool_name:
            continue
        history.append(
            {
                "callId": call_id,
                "toolName": tool_name,
                "arguments": dict(getattr(tool_call, "arguments", {}) or {}),
            }
        )
    conversation.metadata[TOOL_CALL_HISTORY_METADATA_KEY] = history
    return tuple(history)
