"""Compatibility shim — moved to agent.models.providers.github_copilot."""
import sys

from TerraFin.agent.models.providers import github_copilot as _real

sys.modules[__name__] = _real
