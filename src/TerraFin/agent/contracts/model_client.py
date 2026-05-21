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

from typing import TYPE_CHECKING, Protocol

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


class TerraFinHostedModelClient(Protocol):
    def complete(
        self,
        *,
        agent: "TerraFinAgentDefinition",
        session: "TerraFinAgentSession",
        conversation: "TerraFinHostedConversation",
        messages: "tuple[TerraFinConversationMessage, ...]",
        tools: "tuple[TerraFinToolDefinition, ...]",
    ) -> "TerraFinModelTurn": ...


__all__ = ["TerraFinHostedModelClient"]
