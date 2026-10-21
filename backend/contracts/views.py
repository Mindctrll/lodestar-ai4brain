"""Read models for the dashboard (docs/plan/13). Every number comes with its range."""

from uuid import UUID

from pydantic import AwareDatetime, Field

from backend.contracts.common import Contract, DimensionId
from backend.contracts.events import HistoryRow

STILL_LEARNING_SIGMA = 0.8


class DimensionView(Contract):
    dim: DimensionId
    mu: float
    sigma: float = Field(description="With staleness drift applied at read time")
    n: int
    last_practised: AwareDatetime | None
    percent: float
    percent_low: float
    percent_high: float
    norms: str = Field(description="'simulated' until NCPT norms exist for this skill")
    still_learning: bool = Field(description="Shown greyed: 'still learning about you'")


class TwinView(Contract):
    user_id: UUID
    as_of: AwareDatetime
    dims: list[DimensionView]
    history: list[HistoryRow]


class AcsComponentView(Contract):
    code: str
    name: str
    successes: int
    opportunities: int
    score: float = Field(description="Posterior mean, 0-1")
    low: float
    high: float
    weight: float = Field(description="Effective weight; 0 while there isn't enough data")
    enough_data: bool


class AcsView(Contract):
    """The AI Collaboration Score (docs/plan/11): a value with its 80% range, or none yet."""

    score: float | None
    low: float | None
    high: float | None
    components: list[AcsComponentView]


class CreatedUser(Contract):
    user_id: UUID
    token: str = Field(description="Bearer token; shown once, stored only as a hash")


class IngestResult(Contract):
    accepted: int
    duplicates: int
