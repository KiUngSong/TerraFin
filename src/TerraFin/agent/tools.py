from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .definitions import TerraFinAgentDefinition
from .hosted_runtime import (
    TerraFinAgentApprovalRequiredError,
    TerraFinHostedAgentRuntime,
)
from .runtime import TerraFinCapability, TerraFinTaskRecord
from .tool_contracts import HOSTED_TOOL_CONTRACT_VERSION, get_hosted_tool_contract


ToolExecutionMode = Literal["invoke", "task"]


@dataclass(frozen=True, slots=True)
class TerraFinToolDefinition:
    name: str
    capability_name: str
    description: str
    input_schema: dict[str, Any]
    execution_mode: ToolExecutionMode = "invoke"
    side_effecting: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_function_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True, slots=True)
class TerraFinToolInvocationResult:
    tool_name: str
    capability_name: str
    session_id: str
    execution_mode: ToolExecutionMode
    payload: dict[str, Any]
    task: TerraFinTaskRecord | None = None


class TerraFinHostedToolAdapter:
    def __init__(self, runtime: TerraFinHostedAgentRuntime) -> None:
        self.runtime = runtime

    def list_tools_for_agent(self, agent_name: str) -> tuple[TerraFinToolDefinition, ...]:
        definition = self.runtime.get_agent_definition(agent_name)
        return self._tools_for_definition(definition)

    def list_tools_for_session(self, session_id: str) -> tuple[TerraFinToolDefinition, ...]:
        definition = self.runtime.get_session_definition(session_id)
        return self._tools_for_definition(definition)

    def list_function_tools_for_agent(self, agent_name: str) -> list[dict[str, Any]]:
        return [tool.as_function_tool() for tool in self.list_tools_for_agent(agent_name)]

    def list_function_tools_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [tool.as_function_tool() for tool in self.list_tools_for_session(session_id)]

    def get_tool_for_agent(self, agent_name: str, tool_name: str) -> TerraFinToolDefinition:
        tools = {tool.name: tool for tool in self.list_tools_for_agent(agent_name)}
        try:
            return tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown TerraFin hosted tool '{tool_name}' for agent '{agent_name}'.") from exc

    def run_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> TerraFinToolInvocationResult:
        tool = self._get_tool_for_session(session_id, tool_name)
        payload: dict[str, Any]
        task: TerraFinTaskRecord | None = None
        resolved_arguments = dict(arguments or {})
        try:
            if tool.name == "current_view_context":
                payload = self.runtime.read_linked_view_context(
                    session_id,
                    view_context_id=_optional_string(resolved_arguments.get("viewContextId")),
                )
            elif tool.execution_mode == "task":
                task = self.runtime.start_task(session_id, tool.capability_name, **resolved_arguments)
                payload = {
                    "accepted": True,
                    "taskId": task.task_id,
                    "status": task.status,
                }
            else:
                payload = self.runtime.invoke(session_id, tool.capability_name, **resolved_arguments)
        except TerraFinAgentApprovalRequiredError as exc:
            payload = {
                "accepted": False,
                "approvalRequired": True,
                "approval": {
                    "approvalId": exc.approval.approval_id,
                    "status": exc.approval.status,
                    "action": exc.approval.action,
                    "capabilityName": exc.approval.capability_name,
                    "toolName": exc.approval.tool_name,
                    "reason": exc.approval.reason,
                },
            }
        return TerraFinToolInvocationResult(
            tool_name=tool.name,
            capability_name=tool.capability_name,
            session_id=session_id,
            execution_mode=tool.execution_mode,
            payload=payload,
            task=task,
        )

    def _get_tool_for_session(self, session_id: str, tool_name: str) -> TerraFinToolDefinition:
        tools = {tool.name: tool for tool in self.list_tools_for_session(session_id)}
        try:
            return tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown TerraFin hosted tool '{tool_name}' for session '{session_id}'.") from exc

    def _tools_for_definition(self, definition: TerraFinAgentDefinition) -> tuple[TerraFinToolDefinition, ...]:
        tools: list[TerraFinToolDefinition] = []
        for capability in self.runtime.capability_registry.list():
            if not definition.allows(capability.name):
                continue
            if capability.name == "open_chart" and not definition.chart_access:
                continue
            tools.append(self._build_tool_definition(capability, execution_mode="invoke"))
            if definition.allow_background_tasks and capability.backgroundable:
                tools.append(self._build_tool_definition(capability, execution_mode="task"))
        tools.append(self._build_current_view_context_tool())
        return tuple(tools)

    def _build_tool_definition(
        self,
        capability: TerraFinCapability,
        *,
        execution_mode: ToolExecutionMode,
    ) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract(capability.name)
        description = capability.description
        tool_name = capability.name
        if execution_mode == "task":
            tool_name = f"start_{capability.name}_task"
            description = f"Start a background TerraFin task for: {capability.description}"

        return TerraFinToolDefinition(
            name=tool_name,
            capability_name=capability.name,
            description=description,
            input_schema=contract["input_schema"],
            execution_mode=execution_mode,
            side_effecting=capability.side_effecting or execution_mode == "task",
            metadata={
                "backgroundable": capability.backgroundable,
                "capabilityName": capability.name,
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

    def _build_current_view_context_tool(self) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract("current_view_context")
        return TerraFinToolDefinition(
            name="current_view_context",
            capability_name="current_view_context",
            description=(
                "Read the user's current TerraFin page/view context when the request depends on "
                "what they are looking at right now. Do not use unless the request is view-dependent."
            ),
            input_schema=contract["input_schema"],
            execution_mode="invoke",
            side_effecting=False,
            metadata={
                "backgroundable": False,
                "capabilityName": "current_view_context",
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
