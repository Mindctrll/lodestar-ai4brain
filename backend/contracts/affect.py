"""Frustration and fatigue estimates (docs/plan/12).

AGENTS.md rule 3: nothing in this module may reach the Brain Twin. Scoring and profile code must
never import it; tests/backend/test_contracts.py checks that.
"""

from typing import Literal

from pydantic import Field

from backend.contracts.common import Contract, Probability

AffectSource = Literal["behaviour", "camera", "voice"]
Mood = Literal["good", "ok", "tough"]

BEHAVIOUR_WEIGHT_MIN = 0.7


class BehaviourSignals(Contract):
    """Signals from play itself: the mandatory, non-biometric path."""

    error_streak: int = Field(default=0, ge=0)
    rt_z: float | None = Field(default=None, description="RT vs the user's own baseline")
    rt_variability_z: float | None = None
    rapid_taps: int = Field(default=0, ge=0)
    hint_burst: bool = False
    quit_mid_game: bool = False
    too_hard_pressed: bool = False
    mood: Mood | None = None


class BiometricCues(Contract):
    """Coarse local cues, only when their consent switches are on. Never stored as raw data.
    Logged as `affect.biometric.cue`; nothing reads that event into the profile (rule 3)."""

    strain_cue: Probability | None = Field(default=None, description="Camera, one per 10 s")
    voice_strain_cue: Probability | None = Field(default=None, description="Voice, per utterance")


CUE_SWITCHES: dict[str, str] = {"strain_cue": "camera", "voice_strain_cue": "voice_tone"}
CUE_SOURCES: dict[str, AffectSource] = {"strain_cue": "camera", "voice_strain_cue": "voice"}


class AffectReading(Contract):
    frustration_p: Probability
    fatigue_p: Probability
    sources: list[AffectSource]
    behaviour_weight: float = Field(
        ge=BEHAVIOUR_WEIGHT_MIN, le=1.0, description="Behaviour weight in the fusion (>= 0.7)"
    )
