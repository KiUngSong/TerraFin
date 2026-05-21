"""Compatibility shim -- moved to agent.guru.personas."""
import sys

from TerraFin.agent.guru import personas as _real

sys.modules[__name__] = _real
