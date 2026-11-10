"""Deep research for the TerraFin Agent: the research agent loop and the document reader it reads with."""

from .agent import Budget, Message, ModelTurn, ResearchModel, ResearchResult, Toolbox, ToolCall, ToolSpec, research
from .flag import (
    DEEPRESEARCH_ENABLED_ENV,
    DEEPRESEARCH_TOOL_NAMES,
    DeepResearchDisabledError,
    deepresearch_enabled,
    require_deepresearch_enabled,
)
from .reader import Document, load_document


__all__ = [
    "DEEPRESEARCH_ENABLED_ENV",
    "DEEPRESEARCH_TOOL_NAMES",
    "Budget",
    "DeepResearchDisabledError",
    "Document",
    "Message",
    "ModelTurn",
    "ResearchModel",
    "ResearchResult",
    "ToolCall",
    "ToolSpec",
    "Toolbox",
    "deepresearch_enabled",
    "load_document",
    "require_deepresearch_enabled",
    "research",
]
