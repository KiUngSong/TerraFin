"""Compatibility shim — moved to agent.models.providers.openai_compatible."""
import sys

from TerraFin.agent.models.providers import openai_compatible as _real

sys.modules[__name__] = _real
