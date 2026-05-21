"""Compatibility shim - moved to agent.storage.session_store."""
import sys
from TerraFin.agent.storage import session_store as _real
sys.modules[__name__] = _real
