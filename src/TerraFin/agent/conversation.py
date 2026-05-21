"""Compatibility shim — moved to agent.contracts.conversation."""
import sys
from TerraFin.agent.contracts import conversation as _real
sys.modules[__name__] = _real
