"""Compatibility shim — moved to agent.contracts.definitions."""
import sys
from TerraFin.agent.contracts import definitions as _real
sys.modules[__name__] = _real
