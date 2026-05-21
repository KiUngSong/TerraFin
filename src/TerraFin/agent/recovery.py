"""Compatibility shim - moved to agent.runtime.recovery."""
import sys

from TerraFin.agent.runtime import recovery as _real

sys.modules[__name__] = _real
