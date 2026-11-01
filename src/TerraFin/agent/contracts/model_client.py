"""Hosted model-client Protocol.

Lives in `contracts/` rather than `loop.py` so provider implementations
(under `agent/providers/`) and any future `agent/models/` subpackage can
depend on it without importing the runtime loop module — that would be a
layering inversion (runtime is the high-level orchestrator; providers and
model clients sit below it).

Forward references to runtime/tooling types are kept as string
annotations and TYPE_CHECKING imports so this module stays free of
behavioural dependencies on the rest of the agent package.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol


if TYPE_CHECKING:
    # Guard required: runtime.loop imports TerraFinHostedModelClient from
    # this module at module top-level, so eagerly importing
    # runtime.session here creates a real circular import
    # (contracts.model_client -> runtime.session -> runtime/__init__ ->
    # runtime.loop -> contracts.model_client).
    from ..runtime.session import TerraFinAgentSession
    from ..tools import TerraFinToolDefinition
    from .conversation import (
        TerraFinConversationMessage,
        TerraFinHostedConversation,
        TerraFinModelTurn,
    )
    from .definitions import TerraFinAgentDefinition


# Set in a tool call's provider_data when the provider could not decode its
# arguments; the call is answered with a retryable error instead of running.
TOOL_ARGUMENTS_INVALID_KEY = "argumentsInvalid"


@dataclass(frozen=True, slots=True)
class TerraFinTurnOptions:
    """Settings for one model request. Never persisted to the conversation."""

    # "none" keeps the tool definitions in the request but forbids calling them.
    tool_choice: Literal["auto", "none"] = "auto"
    # Appended to the provider's system text for this request only.
    pinned_context: str = ""


class TerraFinHostedModelClient(Protocol):
    def complete(
        self,
        *,
        agent: "TerraFinAgentDefinition",
        session: "TerraFinAgentSession",
        conversation: "TerraFinHostedConversation",
        messages: "tuple[TerraFinConversationMessage, ...]",
        tools: "tuple[TerraFinToolDefinition, ...]",
        options: TerraFinTurnOptions | None = None,
    ) -> "TerraFinModelTurn": ...


__all__ = ["TOOL_ARGUMENTS_INVALID_KEY", "TerraFinHostedModelClient", "TerraFinTurnOptions"]
