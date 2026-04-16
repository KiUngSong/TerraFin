from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from .conversation import (
    TerraFinConversationMessage,
    TerraFinToolCall,
    make_tool_result_block,
)
from .tools import TerraFinHostedToolAdapter, TerraFinToolInvocationResult


ToolExecutionOutcomeKind = Literal["success", "retryable_error", "fatal_error"]


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome:
    kind: ToolExecutionOutcomeKind
    invocation: TerraFinToolInvocationResult | None = None
    message: TerraFinConversationMessage | None = None
    error: Exception | None = None
    fingerprint: str | None = None


class ToolExecutionEngine:
    def __init__(self, tool_adapter: TerraFinHostedToolAdapter) -> None:
        self.tool_adapter = tool_adapter

    def execute(self, session_id: str, tool_call: TerraFinToolCall) -> ToolExecutionOutcome:
        try:
            invocation = self.tool_adapter.run_tool(session_id, tool_call.tool_name, tool_call.arguments)
        except Exception as exc:
            return ToolExecutionOutcome(kind="fatal_error", error=exc)
        message = self._build_tool_result_message(tool_call=tool_call, invocation=invocation)
        if invocation.is_error and invocation.retryable:
            return ToolExecutionOutcome(
                kind="retryable_error",
                invocation=invocation,
                message=message,
                fingerprint=self._fingerprint(invocation),
            )
        return ToolExecutionOutcome(kind="success", invocation=invocation, message=message)

    def _build_tool_result_message(
        self,
        *,
        tool_call: TerraFinToolCall,
        invocation: TerraFinToolInvocationResult,
    ) -> TerraFinConversationMessage:
        task_payload = None
        if invocation.task is not None:
            task_payload = {
                "taskId": invocation.task.task_id,
                "status": invocation.task.status,
                "description": invocation.task.description,
            }
        content_payload = {
            "toolName": invocation.tool_name,
            "capabilityName": invocation.capability_name,
            "executionMode": invocation.execution_mode,
            "payload": invocation.payload,
        }
        if task_payload is not None:
            content_payload["task"] = task_payload
        if invocation.is_error:
            content_payload["isError"] = True
            content_payload["retryable"] = invocation.retryable
            content_payload["errorCode"] = invocation.error_code
            content_payload["errorMessage"] = invocation.error_message
        return TerraFinConversationMessage(
            role="tool",
            name=tool_call.tool_name,
            tool_call_id=tool_call.call_id,
            content=json.dumps(content_payload, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "executionMode": invocation.execution_mode,
                "capabilityName": invocation.capability_name,
                "isError": invocation.is_error,
                "retryable": invocation.retryable,
                "errorCode": invocation.error_code,
            },
            blocks=(
                make_tool_result_block(
                    call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    capability_name=invocation.capability_name,
                    execution_mode=invocation.execution_mode,
                    payload=invocation.payload,
                    task=task_payload,
                    is_error=invocation.is_error,
                    retryable=invocation.retryable,
                    error_code=invocation.error_code,
                    error_message=invocation.error_message,
                ),
            ),
        )

    def _fingerprint(self, invocation: TerraFinToolInvocationResult) -> str:
        return "|".join(
            [
                invocation.tool_name,
                invocation.error_code or "",
                invocation.error_message or "",
            ]
        )

