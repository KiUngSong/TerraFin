"""Compatibility shim — moved to agent.tools.execution."""
import sys

from TerraFin.agent.tools import execution as _real

sys.modules[__name__] = _real
