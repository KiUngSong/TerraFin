"""Guru research memo schema and the structured-output tool definition.

`GuruResearchMemo` is the strict pydantic payload every persona subagent must
submit via the `submit_guru_research_memo` tool before terminating.
`GuruRoutePlan` carries orchestrator-side metadata that threads into the
research prompt.
"""

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field, field_validator, model_validator

from ..tools import TerraFinToolDefinition


GuruStance = Literal["bullish", "bearish", "neutral", "abstain"]
# `consult` is the only route type today. It marks a hidden persona subagent
# session that was spawned by a `consult_<persona>` tool-call from the main
# orchestrator agent (see `docs/agent/architecture.md#orchestrator--persona-subagents`).
# Legacy literal values stay in the type for transcript-log replay of sessions
# created before the orchestrator-as-tool refactor.
GuruRouteType = Literal["consult", "explicit", "portfolio", "macro", "valuation"]

WARREN_BUFFETT = "warren-buffett"
HOWARD_MARKS = "howard-marks"
STANLEY_DRUCKENMILLER = "stanley-druckenmiller"


@dataclass(frozen=True, slots=True)
class GuruRoutePlan:
    """Metadata threaded into a persona subagent's research prompt.

    Under the orchestrator-as-tool architecture, each `consult_<persona>`
    call produces one plan scoped to one guru (`selected_gurus` is always
    length-1 for new-style plans). The shape is kept for transcript-log
    continuity and to avoid rewriting `_run_guru_research_memo` /
    `_build_guru_research_prompt` -- they accept this dataclass.
    """
    route_type: GuruRouteType = "consult"
    selected_gurus: tuple[str, ...] = ()
    reason: str = ""
    matched_terms: tuple[str, ...] = ()
    view_context: dict[str, Any] | None = None


class GuruResearchMemo(BaseModel):
    guru: str
    stance: GuruStance
    confidence: int = Field(ge=0, le=100)
    thesis: str = Field(min_length=1)
    key_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)

    @field_validator("key_evidence", "risks", "open_questions", "citations", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="after")
    def _clamp_unsupported_confidence(self) -> "GuruResearchMemo":
        # A persona that claims high conviction without any citations is almost
        # always overstating. Clamp to keep the orchestrator from treating an
        # unsupported guess as a strong signal. The orchestrator surfaces the
        # note appended to `thesis` so the user sees why confidence dropped.
        if self.confidence >= 80 and not self.citations:
            self.confidence = 60
            note = "(confidence reduced: no citations supplied)"
            if note not in self.thesis:
                self.thesis = f"{self.thesis.rstrip()} {note}"
        return self


_GURU_MEMO_TOOL_NAME = "submit_guru_research_memo"
_GURU_MEMO_TOOL_DESCRIPTION = "Submit the final structured guru research memo after you finish tool-based research."


def _build_guru_memo_tool() -> TerraFinToolDefinition:
    schema = GuruResearchMemo.model_json_schema()
    schema["additionalProperties"] = False
    return TerraFinToolDefinition(
        name=_GURU_MEMO_TOOL_NAME,
        capability_name=_GURU_MEMO_TOOL_NAME,
        description=_GURU_MEMO_TOOL_DESCRIPTION,
        input_schema=schema,
        execution_mode="invoke",
        side_effecting=False,
        metadata={"internalOnly": True, "role": "guruMemo"},
    )


def _validate_guru_memo_arguments(
    *,
    guru_name: str,
    arguments: Mapping[str, Any],
) -> GuruResearchMemo:
    payload = dict(arguments)
    payload["guru"] = guru_name
    return GuruResearchMemo.model_validate(payload)
