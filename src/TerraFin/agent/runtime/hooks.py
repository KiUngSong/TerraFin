"""Turn lifecycle hooks for the hosted agent loop.

The loop runs a fixed, in-repo list of hooks (`default_turn_hooks`). This is a
bounded exception to the rule against plugin hooks: nothing outside this repo
registers one, and a hook adds context or observes a turn, never gates it.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from ..contracts.conversation import TerraFinHostedConversation
from ..tools import TerraFinToolInvocationResult


if TYPE_CHECKING:
    from .loop import TerraFinHostedAgentLoop


class TerraFinTurnHook(Protocol):
    """One turn's lifecycle seams. Every method defaults to a no-op.

    The loop logs and skips a hook call that raises, so a hook never fails a turn.
    """

    def before_turn(self, session_id: str, content: str, conversation: TerraFinHostedConversation) -> Any:
        """Runs after completions are drained and before the user message is appended.

        A message the hook appends to the conversation here counts as this turn's.
        """
        return None

    def pinned_context(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
        state: Any,
    ) -> str | None:
        """Text for one model request's instructions, given `before_turn`'s state.

        Called before every model request of the turn. The text is never persisted.
        """
        return None

    def after_tool(self, session_id: str, invocation: TerraFinToolInvocationResult) -> None:
        return None

    def after_completion(self, session_id: str, marker: Mapping[str, Any], result: Any) -> None:
        """Runs once per background completion delivered into the conversation."""
        return None

    def owned_metadata_tags(self) -> frozenset[str]:
        """Metadata tags of messages this hook re-adds each turn.

        The loop drops such messages before `before_turn` and leaves them out
        of the session's message cap.
        """
        return frozenset()


def default_turn_hooks(loop: "TerraFinHostedAgentLoop") -> tuple[TerraFinTurnHook, ...]:
    """The hooks every loop runs unless it is given its own. None ship yet."""
    return ()
