"""Hosted-runtime exception types."""
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ..storage.session_store import TerraFinHostedApprovalRequest


class TerraFinAgentPolicyError(RuntimeError):
    """Raised when an agent definition attempts to exceed its allowed scope."""


class TerraFinAgentApprovalRequiredError(RuntimeError):
    """Raised when a hosted agent action requires a human approval checkpoint."""

    def __init__(self, approval: "TerraFinHostedApprovalRequest") -> None:
        self.approval = approval
        super().__init__(approval.reason)


class TerraFinAgentSessionConflictError(RuntimeError):
    """Raised when a hosted session lifecycle action conflicts with active runtime state."""
