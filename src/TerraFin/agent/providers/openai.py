"""Compatibility shim — moved to agent.models.providers.openai."""
import sys

from TerraFin.agent.models.providers import openai as _real

sys.modules[__name__] = _real
