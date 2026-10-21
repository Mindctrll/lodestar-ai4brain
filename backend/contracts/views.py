"""Read models for the dashboard (docs/plan/13). Every number comes with its range."""

import datetime as dt
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


class CurvePoint(Contract):
    """One day of a skill's history, in percent with its 80% range (progress curves)."""

    day: dt.date
    dim: DimensionId
    percent: float
    low: float
    high: float
    n: int


class TwinView(Contract):
    user_id: UUID
    as_of: AwareDatetime
    dims: list[DimensionView]
    history: list[HistoryRow]
    curves: list[CurvePoint] = Field(default_factory=list)


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


class GoalView(Contract):
    """A range goal and how far along it is (UW11): the range now against the target."""

    goal_id: UUID
    dim: DimensionId
    name: str
    target: float = Field(description="Aim: the 80% range within ± this many points")
    due: dt.date
    status: str
    range_now: float | None = Field(description="± points now; None before the first round")
    low: float | None
    high: float | None
    rounds_left: int | None = Field(description="About how many more rounds it takes")
    met: bool


class ForecastView(Contract):
    """A growth forecast in percent, always as an 80% range (AGENTS.md rule 5)."""

    dim: DimensionId
    name: str
    sessions_ahead: int
    low: float
    median: float
    high: float
    model_version: str
    note: str


class StatPills(Contract):
    streak_days: int = Field(description="Days in a row with a session, up to today or yesterday")
    rounds_this_week: int
    skills_measured: int
    skills_total: int


class ContextStrip(Contract):
    label: str
    start: AwareDatetime
    end: AwareDatetime


class SkillWeekHeatmap(Contract):
    """Skill x week: rounds played, and the change in the estimate (percentage points)."""

    skills: list[DimensionId]
    weeks: list[dt.date] = Field(description="Monday of each week, oldest first")
    rounds: list[list[int]]
    change: list[list[float | None]]


class HourHeatmap(Contract):
    """Time of day x weekday, in the user's time zone: share of answers right. Cells with fewer
    than `min_answers` answers are left empty rather than guessed."""

    weekdays: list[str]
    hours: list[str]
    accuracy: list[list[float | None]]
    answers: list[list[int]]
    min_answers: int


class ProgressView(Contract):
    stats: StatPills
    life_context: list[ContextStrip]
    by_week: SkillWeekHeatmap
    by_hour: HourHeatmap


class TraceRow(Contract):
    node: str
    event: str
    ms: float | None
    ts: AwareDatetime
