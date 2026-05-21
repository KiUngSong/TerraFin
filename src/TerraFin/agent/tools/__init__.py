"""Hosted-tool adapter, type/result dataclasses, normalization helpers, and
the tool execution engine.

Public surface preserved for backwards-compatibility with the previous flat
`agent.tools` module: every public symbol exposed by the old `agent/tools.py`
plus the `ToolExecutionMode` literal alias is re-exported here.
"""
from .adapter import TerraFinHostedToolAdapter
from .types import (
    ToolExecutionMode,
    TerraFinToolDefinition,
    TerraFinToolInvocationResult,
)


__all__ = [
    "ToolExecutionMode",
    "TerraFinToolDefinition",
    "TerraFinToolInvocationResult",
    "TerraFinHostedToolAdapter",
]
