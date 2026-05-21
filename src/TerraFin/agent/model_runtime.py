"""Compatibility shim — moved to agent.models.runtime."""
import sys

from TerraFin.agent.models import runtime as _real

sys.modules[__name__] = _real
