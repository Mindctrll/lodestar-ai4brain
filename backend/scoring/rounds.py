"""Score one round: from trials to updated beliefs (docs/plan/07). Pure; no database access."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from backend.contracts.trial import TrialEvent
from backend.registry.models import Game
from backend.scoring.hshs import hshs_success
from backend.scoring.kalman_elo import Belief, add_process_noise, predict, update
from backend.scoring.levels import b_for_level
from backend.scoring.loadings import update_weight
from backend.scoring.quality import (
    ANTICIPATION_MS,
    QualityReport,
    TrialSample,
    assess_quality,
)

ABILITY_SCORING = {"binary", "hshs", "span", "continuous", "rubric"}


@dataclass(frozen=True)
class ItemObservation:
    level: float
    b: float
    score: float
    predicted: float


@dataclass(frozen=True)
class RoundOutcome:
    beliefs: dict[str, Belief]
    observations: int
    anticipations_dropped: int
    mean_score: float | None
    quality: QualityReport
    items: list[ItemObservation]


def _deadline(game: Game, trial: TrialEvent) -> float | None:
    raw = trial.stimulus.get("deadline_ms")
    if isinstance(raw, int | float) and raw > 0:
        return float(raw)
    knob = game.knobs.get("deadline_ms")
    return knob.at(trial.level) if knob else None


def observed_score(game: Game, trial: TrialEvent, device_lag_ms: float = 0.0) -> float | None:
    """S in [0, 1] for one trial, or None when it doesn't count (practice, anticipation, no
    answer to score)."""
    if trial.practice or game.scoring not in ABILITY_SCORING:
        return None
    rt = None if trial.rt_ms is None else max(0.0, trial.rt_ms - device_lag_ms)
    if rt is not None and rt < ANTICIPATION_MS:
        return None
    if game.scoring in {"continuous", "rubric"}:
        raw = trial.response.get("score") if trial.response else None
        if isinstance(raw, int | float):
            return min(max(float(raw), 0.0), 1.0)
    if trial.correct is None:
        return None
    if game.scoring == "hshs" and rt is not None:
        deadline = _deadline(game, trial)
        if deadline:
            return hshs_success(trial.correct, rt, deadline)
    return 1.0 if trial.correct else 0.0


def score_round(
    game: Game,
    trials: Sequence[TrialEvent],
    beliefs: Mapping[str, Belief],
    loadings: Mapping[str, float],
    *,
    context_weight: float = 1.0,
    device_lag_ms: float = 0.0,
    item_b: Mapping[float, float] | None = None,
    chance: float = 0.5,
) -> RoundOutcome:
    """Apply every counting trial to every dimension the game loads on.

    `loadings` comes from `loading_matrix(registry)[game.id]`; `item_b` maps a level to its learned
    difficulty (from twin.item_difficulty) when one exists.
    """
    counted = [t for t in trials if not t.practice]
    quality = assess_quality(
        [TrialSample(t.correct, t.rt_ms) for t in counted],
        chance=chance,
    )
    updated = {dim: add_process_noise(beliefs[dim]) for dim in loadings}
    primary = max(loadings, key=lambda d: loadings[d]) if loadings else None
    scores: list[float] = []
    items: list[ItemObservation] = []
    anticipations = 0
    last_ts: datetime | None = None

    for trial in sorted(counted, key=lambda t: (t.trial_index, t.ts)):
        if trial.rt_ms is not None and trial.rt_ms - device_lag_ms < ANTICIPATION_MS:
            anticipations += 1
        s = observed_score(game, trial, device_lag_ms)
        if s is None:
            continue
        b = (item_b or {}).get(trial.level, b_for_level(trial.level))
        if primary is not None:
            items.append(ItemObservation(trial.level, b, s, predict(updated[primary], b)))
        for dim, loading in loadings.items():
            w = update_weight(loading, game.effective_reliability, context_weight, quality.trust)
            updated[dim] = update(updated[dim], b, s, w)
        scores.append(s)
        last_ts = trial.ts if last_ts is None else max(last_ts, trial.ts)

    if last_ts is not None and quality.trust > 0:
        updated = {d: replace(b, last_practised=last_ts) for d, b in updated.items()}
    if not scores or quality.trust == 0:
        # Nothing counted: keep the beliefs exactly as they were (no process noise either).
        updated = {dim: beliefs[dim] for dim in loadings}
    return RoundOutcome(
        beliefs=updated,
        observations=len(scores) if quality.trust > 0 else 0,
        anticipations_dropped=anticipations,
        mean_score=sum(scores) / len(scores) if scores else None,
        quality=quality,
        items=items,
    )
