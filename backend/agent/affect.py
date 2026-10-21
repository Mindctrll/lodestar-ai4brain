"""Frustration and fatigue from behaviour (docs/plan/12, "the main path"). Rule-based for now
(P1); WP3.3 fits a model on the mood-check and "Was I right?" labels.

What it can do: ease difficulty, switch to a lighter game, suggest a break, soften the coach's
tone. What it can't do: change the profile or appear in any score (AGENTS.md rule 3).

Optional camera and voice cues (WP3.5, WP3.9) are fused at weight 0.3 at most:
affect = 0.7 x behaviour + 0.3 x mean(cues). They only add a break suggestion and soften the
coach's tone; easing and stopping follow behaviour alone (monitor in backend/agent/nodes/play.py).
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.contracts.affect import (
    BEHAVIOUR_WEIGHT_MIN,
    CUE_SOURCES,
    CUE_SWITCHES,
    AffectReading,
    AffectSource,
    BehaviourSignals,
)
from backend.contracts.exercise import RoundResult
from backend.db import tables as t


def frustration_from_behaviour(round_result: RoundResult | None, accuracy: float | None) -> float:
    if round_result is None:
        return 0.0
    p = 0.0
    if round_result.stop_reason == "frustration" or round_result.status == "eased":
        p = 0.8
    elif round_result.status == "stopped":
        p = 0.6
    b = round_result.behaviour
    if b is not None:
        if b.mood == "tough":
            p = max(p, 0.8)
        if b.too_hard_pressed or b.quit_mid_game or b.error_streak >= 4:
            p = max(p, 0.75)
        elif b.error_streak >= 3:
            p = max(p, 0.55)
        if b.rapid_taps >= 3:
            p = max(p, 0.6)
        if b.hint_burst or (b.rt_variability_z is not None and b.rt_variability_z > 2):
            p = max(p, 0.5)
    if accuracy is not None and accuracy < 0.4:
        p = max(p, 0.6)
    return p


def fatigue_from_behaviour(behaviour: BehaviourSignals | None, session_fatigue: float) -> float:
    slow = behaviour is not None and behaviour.rt_z is not None and behaviour.rt_z > 1.5
    return max(session_fatigue, 0.6 if slow else 0.0)


def estimate(
    round_result: RoundResult | None,
    accuracy: float | None,
    session_fatigue: float,
    cues: Sequence[tuple[AffectSource, float]] = (),
) -> AffectReading:
    frustration = frustration_from_behaviour(round_result, accuracy)
    fatigue = fatigue_from_behaviour(
        round_result.behaviour if round_result else None, session_fatigue
    )
    sources: list[AffectSource] = ["behaviour"]
    weight = 1.0
    if cues:
        weight = BEHAVIOUR_WEIGHT_MIN
        mean_cue = sum(v for _, v in cues) / len(cues)
        frustration = weight * frustration + (1 - weight) * mean_cue
        fatigue = weight * fatigue + (1 - weight) * mean_cue
        sources += [s for s, _ in cues if s not in sources]
    return AffectReading(
        frustration_p=round(frustration, 3),
        fatigue_p=round(fatigue, 3),
        sources=sources,
        behaviour_weight=weight,
    )


async def recent_cues(
    conn: AsyncConnection,
    user_id: UUID,
    session_id: UUID,
    since: datetime,
    consent: frozenset[str],
) -> list[tuple[AffectSource, float]]:
    """The latest camera and voice cue of this session since `since`, for switches still on."""
    rows = await conn.execute(
        select(t.events.c.payload)
        .where(
            t.events.c.user_id == user_id,
            t.events.c.session_id == session_id,
            t.events.c.type == "affect.biometric.cue",
            t.events.c.ts >= since,
        )
        .order_by(t.events.c.ts)
    )
    latest: dict[str, float] = {}
    for (payload,) in rows:
        latest.update({k: v for k, v in payload.items() if v is not None})
    return [(CUE_SOURCES[k], float(v)) for k, v in latest.items() if CUE_SWITCHES[k] in consent]
