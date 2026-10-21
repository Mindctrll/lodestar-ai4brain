"""The append-only event log `twin.events` (docs/plan/04). One class per event type.

The `type` field discriminates the union, so `Event` parses any stored row back into its class.
"""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, TypeAdapter

from backend.contracts.acs import AcsEvent
from backend.contracts.affect import AffectReading, BiometricCues
from backend.contracts.common import (
    ConsentSwitch,
    Contract,
    DimensionId,
    Persona,
    ProviderId,
    SuccessMode,
    Trigger,
)
from backend.contracts.exercise import RoundResult
from backend.contracts.llm import LlmMode
from backend.contracts.trial import TrialEvent
from backend.contracts.twin import DimensionState, LifeContextWindow

# Payloads -------------------------------------------------------------------------------------


class SessionStartedPayload(Contract):
    trigger: Trigger
    persona: Persona


class DimensionChange(Contract):
    dim: DimensionId
    mu_before: float
    mu_after: float
    sigma_before: float
    sigma_after: float
    n_after: int
    last_practised_after: AwareDatetime | None = None


class ScoringInputs(Contract):
    """Everything outside the trials that shaped the update, so a rebuild or re-score of the
    event log reproduces it exactly (item difficulties change as other users play)."""

    context_weight: float = Field(ge=0.0, le=1.0)
    item_b: dict[str, float] = Field(default_factory=dict, description="level -> difficulty used")
    device_lag_ms: float = 0.0
    trust: float = Field(ge=0.0, le=1.0)
    quality_verdict: str
    practice_a: float | None = Field(
        default=None, description="Prediction step used: gain per round = a * k^-b (Lumosity)"
    )
    practice_b: float | None = None


class TwinUpdatedPayload(Contract):
    round_id: UUID
    changes: list[DimensionChange]
    inputs: ScoringInputs


class GoalPayload(Contract):
    goal_id: UUID
    dim: DimensionId
    kind: Literal["range", "score"]
    target: float
    due: dt.date


class ExperimentPayload(Contract):
    exp_id: UUID
    hypothesis: str | None = None
    condition: str | None = None
    result: dict[str, JsonValue] | None = None


class ConsentPayload(Contract):
    switch: ConsentSwitch
    granted: bool
    notice_version: str


class MemoryWrittenPayload(Contract):
    point_id: UUID
    collection: Literal["episodic", "facts"]
    kind: str
    importance: float


class AffectLabelPayload(Contract):
    """A label from the user: a one-tap mood after a round, or "Was I right?" about a guess."""

    kind: Literal["mood", "was_i_right"]
    value: str = Field(max_length=20)
    round_id: UUID | None = None
    decision_id: UUID | None = None


class SettingsChangedPayload(Contract):
    """A setting the user changed by chat or in Settings. Only the fields that changed are set."""

    persona: Persona | None = None
    success_mode: SuccessMode | None = None
    paused_dim: DimensionId | None = Field(
        default=None, description="A skill Najma stops suggesting until `paused_until`"
    )
    paused_until: AwareDatetime | None = None


class SessionEndedPayload(Contract):
    reason: Literal["budget", "fatigue", "user", "break", "error"]
    rounds: int = Field(ge=0)
    minutes: float = Field(ge=0)


class DataExportedPayload(Contract):
    counts: dict[str, int]


class HistoryRow(Contract):
    day: dt.date
    dim: DimensionId
    mu: float
    sigma: float
    n: int


class TwinSnapshotPayload(Contract):
    """Written by the retention job before it drops an old partition."""

    dims: list[DimensionState]
    history: list[HistoryRow]
    covers_until: AwareDatetime


class LlmSelectionPayload(Contract):
    mode: LlmMode
    provider: ProviderId
    model: str


class StoryChapterPayload(Contract):
    story_id: str
    chapter: int = Field(ge=1, description="The chapter just finished, from 1")
    chapters: int = Field(ge=1)
    round_id: UUID


# Envelopes ------------------------------------------------------------------------------------


class _Envelope(Contract):
    event_id: UUID | None = Field(default=None, description="Assigned by Postgres (uuidv7)")
    user_id: UUID
    session_id: UUID | None = None
    ts: AwareDatetime
    schema_version: int = 1


class SessionStarted(_Envelope):
    type: Literal["session.started"] = "session.started"
    payload: SessionStartedPayload


class TrialRecorded(_Envelope):
    type: Literal["trial.recorded"] = "trial.recorded"
    payload: TrialEvent


class RoundCompleted(_Envelope):
    type: Literal["round.completed"] = "round.completed"
    payload: RoundResult


class TwinUpdated(_Envelope):
    type: Literal["twin.updated"] = "twin.updated"
    payload: TwinUpdatedPayload


class AcsObserved(_Envelope):
    type: Literal["acs.observed"] = "acs.observed"
    payload: AcsEvent


class AffectEstimated(_Envelope):
    type: Literal["affect.estimated"] = "affect.estimated"
    payload: AffectReading


class AffectLabelled(_Envelope):
    type: Literal["affect.labelled"] = "affect.labelled"
    payload: AffectLabelPayload


class AffectBiometricCue(_Envelope):
    """A coarse camera or voice cue (WP3.5, WP3.9). Event log only: AGENTS.md rule 3."""

    type: Literal["affect.biometric.cue"] = "affect.biometric.cue"
    payload: BiometricCues


class ContextAdded(_Envelope):
    type: Literal["context.added"] = "context.added"
    payload: LifeContextWindow


class GoalSet(_Envelope):
    type: Literal["goal.set"] = "goal.set"
    payload: GoalPayload


class ExperimentStarted(_Envelope):
    type: Literal["experiment.started"] = "experiment.started"
    payload: ExperimentPayload


class ExperimentSessionLogged(_Envelope):
    type: Literal["experiment.session_logged"] = "experiment.session_logged"
    payload: ExperimentPayload


class ExperimentCompleted(_Envelope):
    type: Literal["experiment.completed"] = "experiment.completed"
    payload: ExperimentPayload


class ConsentChanged(_Envelope):
    type: Literal["consent.changed"] = "consent.changed"
    payload: ConsentPayload


class MemoryWritten(_Envelope):
    type: Literal["memory.written"] = "memory.written"
    payload: MemoryWrittenPayload


class SettingsChanged(_Envelope):
    type: Literal["settings.changed"] = "settings.changed"
    payload: SettingsChangedPayload


class SessionEnded(_Envelope):
    type: Literal["session.ended"] = "session.ended"
    payload: SessionEndedPayload


class DataExported(_Envelope):
    type: Literal["data.exported"] = "data.exported"
    payload: DataExportedPayload


class TwinSnapshotTaken(_Envelope):
    type: Literal["twin.snapshot"] = "twin.snapshot"
    payload: TwinSnapshotPayload


class LlmSelectionChanged(_Envelope):
    type: Literal["llm.selection_changed"] = "llm.selection_changed"
    payload: LlmSelectionPayload


class StoryChapterCompleted(_Envelope):
    type: Literal["story.chapter_completed"] = "story.chapter_completed"
    payload: StoryChapterPayload


Event = Annotated[
    SessionStarted
    | TrialRecorded
    | RoundCompleted
    | TwinUpdated
    | AcsObserved
    | AffectEstimated
    | AffectLabelled
    | AffectBiometricCue
    | ContextAdded
    | GoalSet
    | ExperimentStarted
    | ExperimentSessionLogged
    | ExperimentCompleted
    | ConsentChanged
    | MemoryWritten
    | SettingsChanged
    | SessionEnded
    | DataExported
    | TwinSnapshotTaken
    | LlmSelectionChanged
    | StoryChapterCompleted,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

EVENT_TYPES: tuple[str, ...] = tuple(
    cls.model_fields["type"].default for cls in _Envelope.__subclasses__()
)


def parse_event(data: dict[str, Any]) -> Event:
    return EVENT_ADAPTER.validate_python(data)
