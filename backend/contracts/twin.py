"""The Brain Twin: per-skill beliefs, forecasts and life context (docs/plan/07, 10)."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.common import Contract, DimensionId, Probability


class DimensionState(Contract):
    dim: DimensionId
    mu: float = Field(description="Belief mean on the logit scale")
    sigma: float = Field(gt=0.0, description="Belief standard deviation")
    n: int = Field(ge=0, description="Scored answers so far")
    last_practised: AwareDatetime | None = None


class TwinSnapshot(Contract):
    user_id: UUID
    as_of: AwareDatetime
    dims: dict[DimensionId, DimensionState]


class ForecastBand(Contract):
    """A growth forecast is always a range (AGENTS.md rule 5)."""

    dim: DimensionId
    sessions_ahead: int = Field(gt=0)
    low: float
    median: float
    high: float
    nominal_coverage: Probability = 0.8
    source: Literal["model", "prior"]

    @model_validator(mode="after")
    def _ordered(self) -> ForecastBand:
        if not self.low <= self.median <= self.high:
            raise ValueError("forecast band must satisfy low <= median <= high")
        return self


class EngagementReading(Contract):
    """Chance of no activity in the next 7 days, as a Venn-Abers range (docs/plan/10, section 2).
    Used only to offer a shorter, easier session; never shown as a score of the person."""

    low: Probability
    high: Probability
    active_7: int = Field(ge=0, description="Days played in the last 7 days, today included")
    active_prev_7: int = Field(ge=0, description="Days played in the 7 days before")
    model_version: str

    @property
    def high_risk(self) -> bool:
        """Sure enough to act on: even the low end of the range says likely."""
        return self.low >= 0.5


class FatiguePoint(Contract):
    """Minutes into a session when this person's answers usually start to slow down
    (docs/plan/10, section 3): a median with its middle half, from past sessions."""

    low: float = Field(gt=0, description="25th percentile, minutes")
    median: float = Field(gt=0)
    high: float = Field(gt=0, description="75th percentile, minutes")
    sessions: int = Field(ge=1, description="Sessions it rests on")

    @model_validator(mode="after")
    def _ordered(self) -> FatiguePoint:
        if not self.low <= self.median <= self.high:
            raise ValueError("fatigue point must satisfy low <= median <= high")
        return self


class LifeContextWindow(Contract):
    context_id: UUID
    label: str = Field(min_length=1, max_length=80)
    start: AwareDatetime
    end: AwareDatetime
    weight: Probability = Field(description="Scoring weight inside the window (0.5 by default)")

    @model_validator(mode="after")
    def _ordered(self) -> LifeContextWindow:
        if self.end <= self.start:
            raise ValueError("life context must end after it starts")
        return self
