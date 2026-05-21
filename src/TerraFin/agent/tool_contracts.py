"""Compatibility shim — moved to agent.contracts.tool_contracts."""
import sys
from TerraFin.agent.contracts import tool_contracts as _real
sys.modules[__name__] = _real
