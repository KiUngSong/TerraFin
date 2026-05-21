"""Compatibility shim - moved to agent.runtime.context_budget."""
import sys

from TerraFin.agent.runtime import context_budget as _real

sys.modules[__name__] = _real
