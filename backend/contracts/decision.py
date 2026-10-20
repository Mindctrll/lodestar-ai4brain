"""The explainability backbone: every decision leaves a reason (docs/plan/03)."""

from uuid import UUID

from pydantic import AwareDatetime, Field

from backend.contracts.common import Contract


class Candidate(Contract):
    option: str
    score: float
    breakdown: dict[str, float] = Field(
        default_factory=dict, description="Named parts of the score, e.g. uncertainty: 0.31"
    )


class Decision(Contract):
    decision_id: UUID
    node: str
    at: AwareDatetime
    question: str = Field(min_length=1)
    candidates: list[Candidate]
    chosen: str
    reason: str = Field(min_length=1, description="Plain words, shown in the UI")
    evidence: list[str] = Field(default_factory=list, description="Event ids or fact ids")
