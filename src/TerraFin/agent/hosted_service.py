"""Compatibility shim - moved to agent.service.hosted."""
import sys

from TerraFin.agent.service import hosted as _real

sys.modules[__name__] = _real
