"""Product switch for deep research. Default on.

Disable with ``TERRAFIN_AGENT_DEEPRESEARCH_ENABLED=0``. The tools disappear from
the model's tool list while off, so the agent cannot choose a capability the
product has not shipped, and their registry handlers raise
`DeepResearchDisabledError` on any other path. The research loop itself stays
importable, which is what lets the benchmark harness run it without turning
the product path on.
"""

import os


DEEPRESEARCH_ENABLED_ENV = "TERRAFIN_AGENT_DEEPRESEARCH_ENABLED"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

DEEPRESEARCH_TOOL_NAMES = frozenset({"deep_research"})


class DeepResearchDisabledError(RuntimeError):
    """Raised when a product path is called while deep research is off."""

    def __init__(self) -> None:
        super().__init__("Deep research is disabled. Unset TERRAFIN_AGENT_DEEPRESEARCH_ENABLED or set it to 1 to enable.")


def deepresearch_enabled() -> bool:
    raw = os.environ.get(DEEPRESEARCH_ENABLED_ENV, "1").strip().lower()
    return raw in _TRUTHY


def require_deepresearch_enabled() -> None:
    """Raise `DeepResearchDisabledError` unless the flag is on."""
    if not deepresearch_enabled():
        raise DeepResearchDisabledError()
