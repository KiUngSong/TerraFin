"""Tool type / result dataclasses for the TerraFin hosted runtime."""
from dataclasses import dataclass, field
from typing import Any, Literal

from ..runtime.tasks import TerraFinTaskRecord


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
    is_error: bool = False
    retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class _ToolErrorDisposition:
    code: str
    message: str
    retryable: bool
    expose_to_user: bool
    model_hint: str | None = None
