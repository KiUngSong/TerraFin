"""Compatibility shim — moved to agent.models.management."""
import sys

from TerraFin.agent.models import management as _real

sys.modules[__name__] = _real
