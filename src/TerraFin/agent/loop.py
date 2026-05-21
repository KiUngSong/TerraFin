"""Compatibility shim - moved to agent.runtime.loop."""
import sys

from TerraFin.agent.runtime import loop as _real

sys.modules[__name__] = _real
