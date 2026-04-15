from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from openai import APIError

from ..conversation_state import get_provider_state, set_provider_state
from ..definitions import TerraFinAgentDefinition
from ..loop import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinToolCall,
)
from ..runtime import TerraFinAgentSession
from ..tools import TerraFinToolDefinition


class OpenAICompatibleResponsesRunner:
    def __init__(
        self,
        *,
        provider_id: str,
        max_retries: int,
        response_error_cls: type[RuntimeError],
    ) -> None:
        self.provider_id = provider_id
        self.max_retries = max(max_retries, 0)
        self.response_error_cls = response_error_cls

    def complete(
        self,
        *,
        client: Any,
        model_id: str,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
        legacy_response_id: str | None = None,
        legacy_message_cursor: int = 0,
    ) -> TerraFinModelTurn:
        _ = session
        payload = self._build_request_payload(
            model_id=model_id,
            agent=agent,
            conversation=conversation,
            messages=messages,
            tools=tools,
            legacy_response_id=legacy_response_id,
            legacy_message_cursor=legacy_message_cursor,
        )
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.responses.create(**payload)
                break
            except APIError as exc:
                status_code = getattr(exc, "status_code", None)
                retryable = status_code is None or status_code == 429 or int(status_code) >= 500
                if attempt >= self.max_retries or not retryable:
                    raise self.response_error_cls(str(exc)) from exc
            except Exception as exc:
                raise self.response_error_cls(str(exc)) from exc
        if response is None:
            raise self.response_error_cls("Provider SDK did not return a response payload.")
        data = self._to_payload(response)
        response_id = data.get("id")
        if not response_id:
            raise self.response_error_cls("Provider response did not include an id.")

        set_provider_state(
            conversation,
            self.provider_id,
            {
                "responseId": response_id,
                "messageCursor": len(conversation.messages),
            },
        )

        tool_calls = self._extract_tool_calls(data)
        assistant_text = self._extract_assistant_text(data)
        assistant_message = (
            TerraFinConversationMessage(role="assistant", content=assistant_text) if assistant_text else None
        )
        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason="tool_calls" if tool_calls else "completed",
        )

    def _build_request_payload(
        self,
        *,
        model_id: str,
        agent: TerraFinAgentDefinition,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
        legacy_response_id: str | None,
        legacy_message_cursor: int,
    ) -> dict[str, Any]:
        state = get_provider_state(conversation, self.provider_id)
        previous_response_id = str(state.get("responseId") or legacy_response_id or "").strip() or None
        cursor_value = state.get("messageCursor", legacy_message_cursor)
        try:
            cursor = max(int(cursor_value), 0)
        except Exception:
            cursor = 0

        if previous_response_id and cursor <= len(messages):
            input_items = self._messages_to_input(messages[cursor:])
        else:
            input_items = self._messages_to_input(messages)
            previous_response_id = None

        payload: dict[str, Any] = {
            "model": model_id,
            "tools": [self._tool_to_openai(tool) for tool in tools],
            "input": input_items,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if not previous_response_id:
            payload["instructions"] = (
                f"Stay within the hosted TerraFin agent definition '{agent.name}' and use tools when they improve accuracy."
            )
        return payload

    def _messages_to_input(
        self,
        messages: tuple[TerraFinConversationMessage, ...],
    ) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "assistant":
                continue
            if message.role == "tool":
                if not message.tool_call_id:
                    continue
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            input_items.append(
                {
                    "type": "message",
                    "role": message.role,
                    "content": [{"type": "input_text", "text": message.content}],
                }
            )
        return input_items

    def _tool_to_openai(self, tool: TerraFinToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }

    def _extract_tool_calls(self, payload: Mapping[str, Any]) -> tuple[TerraFinToolCall, ...]:
        calls: list[TerraFinToolCall] = []
        for item in payload.get("output", []):
            if not isinstance(item, Mapping) or item.get("type") != "function_call":
                continue
            arguments_raw = item.get("arguments")
            if isinstance(arguments_raw, str) and arguments_raw.strip():
                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError as exc:
                    raise self.response_error_cls(
                        f"Provider function_call arguments for '{item.get('name')}' were not valid JSON."
                    ) from exc
            else:
                arguments = {}
            if not isinstance(arguments, Mapping):
                raise self.response_error_cls(
                    f"Provider function_call arguments for '{item.get('name')}' must decode to an object."
                )
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            tool_name = str(item.get("name") or "").strip()
            if not call_id or not tool_name:
                raise self.response_error_cls("Provider function_call response was missing call_id or name.")
            calls.append(
                TerraFinToolCall(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                )
            )
        return tuple(calls)

    def _extract_assistant_text(self, payload: Mapping[str, Any]) -> str:
        texts: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                continue
            for content in item.get("content", []):
                if not isinstance(content, Mapping):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        if texts:
            return "\n".join(texts).strip()
        output_text = payload.get("output_text")
        return output_text.strip() if isinstance(output_text, str) else ""

    def _to_payload(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            payload = response.model_dump(mode="python")
            if isinstance(payload, dict):
                return payload
        if isinstance(response, Mapping):
            return dict(response)
        raise self.response_error_cls("Provider SDK returned an unexpected response payload.")
