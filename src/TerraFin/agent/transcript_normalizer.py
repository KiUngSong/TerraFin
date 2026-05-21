"""Compatibility shim - moved to agent.runtime.transcript_normalizer."""
import sys

from TerraFin.agent.runtime import transcript_normalizer as _real

sys.modules[__name__] = _real
