"""Hidden investor-persona subagents for the main TerraFin Agent.

The user-facing product surface stays as a single TerraFin Agent. That
main assistant acts as the **orchestrator**: it decides, per-turn, whether
to consult one or more hidden investor-persona subagents (Warren Buffett,
Howard Marks, Stanley Druckenmiller) by calling a ``consult_<persona>``
tool. The LLM makes that decision with context in hand -- this package no
longer gates behaviour on a regex router; it exposes the memo-generation
machinery the orchestrator drives via tool-calls.

Public entry point: :func:`run_guru_consult`.
"""

from .consult import run_guru_consult
from .feedback import _persona_fit_feedback
from .memo import (
    HOWARD_MARKS,
    STANLEY_DRUCKENMILLER,
    WARREN_BUFFETT,
    GuruResearchMemo,
    GuruRoutePlan,
    GuruRouteType,
    GuruStance,
    _build_guru_memo_tool,
    _validate_guru_memo_arguments,
)
from .worker import (
    _build_guru_research_prompt,
    _execute_guru_worker,
    _run_guru_research_memo,
    _select_guru_worker_tools,
)


__all__ = [
    "GuruResearchMemo",
    "GuruRoutePlan",
    "GuruRouteType",
    "GuruStance",
    "WARREN_BUFFETT",
    "HOWARD_MARKS",
    "STANLEY_DRUCKENMILLER",
    "_build_guru_memo_tool",
    "_build_guru_research_prompt",
    "_execute_guru_worker",
    "_persona_fit_feedback",
    "_run_guru_research_memo",
    "_select_guru_worker_tools",
    "_validate_guru_memo_arguments",
    "run_guru_consult",
]
