"""Range goals (UW11, docs/plan/07): "your memory range within ±12 points by 3 Nov".

A goal is about certainty, not a score to beat: the 80% range of the percentile estimate shrinks as
Lodestar sees more rounds. Each round adds process noise (Q_ROUND), so the range can't shrink below
a floor; goals are set above it.
"""

import math
from dataclasses import replace

from backend.scoring.kalman_elo import Q_ROUND, SIGMA_START, Belief
from backend.scoring.norms import Norms

TRIALS_PER_ROUND = 10
TRIAL_WEIGHT = 0.8  # loading 1 x a typical reliability
P_TRAIN = 0.8  # Balanced mode success rate
MAX_ROUNDS = 60


def half_range(belief: Belief, dim: str, norms: Norms) -> float:
    """Half the width of the 80% percentile range, in percentage points."""
    pr = norms.percentile(dim, belief)
    return (pr.high - pr.low) / 2


def _after_round(belief: Belief) -> Belief:
    variance = min(SIGMA_START**2, belief.variance + Q_ROUND)
    info = TRIALS_PER_ROUND * TRIAL_WEIGHT * P_TRAIN * (1 - P_TRAIN)
    return replace(belief, sigma=math.sqrt(1.0 / (1.0 / variance + info)))


def rounds_to_target(belief: Belief, dim: str, target: float, norms: Norms) -> int | None:
    """About how many more rounds of this skill bring the range within ±target, or None if more
    than MAX_ROUNDS would be needed."""
    b = belief
    for k in range(MAX_ROUNDS + 1):
        if half_range(b, dim, norms) <= target:
            return k
        b = _after_round(b)
    return None


def range_floor(belief: Belief, dim: str, norms: Norms) -> float:
    """The narrowest range practice can reach at this level: where each round's new evidence just
    balances its process noise."""
    b = belief
    for _ in range(200):
        b = _after_round(b)
    return half_range(b, dim, norms)


def suggest_target(belief: Belief, dim: str, norms: Norms) -> int:
    """A reachable target: about 40% narrower than now, never below the floor plus 2 points.
    Already near the floor, the goal is to keep the range where it is (0 more rounds)."""
    now = half_range(belief, dim, norms)
    floor = math.ceil(range_floor(belief, dim, norms)) + 2
    return min(max(floor, round(now * 0.6)), math.ceil(now))
