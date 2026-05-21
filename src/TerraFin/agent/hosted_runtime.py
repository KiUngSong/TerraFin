"""Compatibility shim - moved to agent.runtime.hosted.

The full hosted-runtime public surface (errors + the orchestrator) is also
re-exported by `agent.runtime`, so external `from TerraFin.agent.runtime
import TerraFinHostedAgentRuntime` continues to work.
"""
import sys

from TerraFin.agent.runtime import hosted as _real

sys.modules[__name__] = _real
