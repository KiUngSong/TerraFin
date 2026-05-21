"""Compatibility shim — moved to agent.contracts.conversation_state."""
import sys
from TerraFin.agent.contracts import conversation_state as _real
sys.modules[__name__] = _real
