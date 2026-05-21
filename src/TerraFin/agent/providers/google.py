"""Compatibility shim — moved to agent.models.providers.google."""
import sys

from TerraFin.agent.models.providers import google as _real

sys.modules[__name__] = _real
