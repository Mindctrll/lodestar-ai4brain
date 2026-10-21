"""The graph state (docs/plan/03, State). Parallel nodes write through reducers.

Run-scoped settings (LLM selection, seed, consent flags) live in the runtime context, not here,
and no API key is ever stored in state (AGENTS.md rule 9).
"""

import operator
from datetime import datetime
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from backend.contracts.acs import AcsEvent
from backend.contracts.affect import AffectReading
from backend.contracts.common import Persona, Trigger
from backend.contracts.decision import Decision
from backend.contracts.exercise import ExerciseSpec, RoundResult
from backend.contracts.facts import CoachReply, FactsPacket
from backend.contracts.memory import MemoryHit
from backend.contracts.session import (
    Intent,
    RoundSummary,
    SessionBudget,
    SessionPlan,
    ToolCall,
    ToolOutcome,
    Verdict,
)
from backend.contracts.twin import (
    EngagementReading,
    FatiguePoint,
    ForecastBand,
    LifeContextWindow,
    TwinSnapshot,
)


class NajmaState(BaseModel):
    # identity and trigger
    user_id: str
    session_id: str
    trigger: Trigger
    persona: Persona
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    said: str | None = Field(default=None, description="What the user said this turn, if anything")

    # perception (filled in parallel)
    twin: TwinSnapshot | None = None
    memories: list[MemoryHit] = Field(default_factory=list)
    affect: AffectReading | None = None
    context: list[LifeContextWindow] = Field(default_factory=list)
    forecast: dict[str, ForecastBand] = Field(default_factory=dict)

    # routing and planning
    intent: Intent | None = None
    decisions: Annotated[list[Decision], operator.add] = Field(default_factory=list)
    plan: SessionPlan | None = None
    exercise: ExerciseSpec | None = None
    declined_dims: Annotated[list[str], operator.add] = Field(
        default_factory=list, description="Skills turned down this session (UW3)"
    )

    # conversation (converse subgraph)
    tool_call: ToolCall | None = None
    confirmed: bool | None = None
    tool_outcome: ToolOutcome | None = None

    # results
    rounds: Annotated[list[RoundResult], operator.add] = Field(default_factory=list)
    acs_events: Annotated[list[AcsEvent], operator.add] = Field(default_factory=list)
    facts: FactsPacket | None = None
    reply: CoachReply | None = None

    last_round: RoundSummary | None = None
    verdict: Verdict | None = None
    onboarding: list[str] = Field(
        default_factory=list, description="Warm-up battery games still to play (UW1)"
    )
    goal_dims: list[str] = Field(default_factory=list, description="Skills with an active goal")
    away_days: float | None = Field(default=None, description="Days since the last session")
    engagement: EngagementReading | None = None
    fatigue_point: FatiguePoint | None = None

    def game_waiting(self) -> bool:
        """A suggested game the user hasn't played yet: chat turns come back to it."""
        if self.exercise is None:
            return False
        return not any(str(r.round_id) == str(self.exercise.round_id) for r in self.rounds)

    # control
    started_at: datetime | None = None
    success_mode: Literal["chill", "balanced", "push"] = "balanced"
    budget: SessionBudget = Field(default_factory=SessionBudget)
    degraded: Annotated[list[str], operator.add] = Field(default_factory=list)
