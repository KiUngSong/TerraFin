"""Compatibility shim - moved to agent.cli.tasks."""
import sys

from TerraFin.agent.cli import tasks as _real

sys.modules[__name__] = _real
