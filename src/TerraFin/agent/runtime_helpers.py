"""Compatibility shim - moved to agent.service.client_helpers (renamed).

The original name was misleading — this module has nothing to do with
runtime internals; it's a client-side convenience wrapper around
``TerraFinAgentClient`` for ad-hoc / notebook usage. The shim preserves
the old import path.
"""
import sys

from TerraFin.agent.service import client_helpers as _real

sys.modules[__name__] = _real
