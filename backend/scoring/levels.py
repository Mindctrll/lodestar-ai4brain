"""Difficulty: level (0..1) <-> item difficulty b <-> knobs, and target selection (docs/plan/07)."""

import math
from typing import Literal

from backend.registry.models import Game
from backend.scoring.kalman_elo import Belief, logit, predict

# Designed difficulty range on the logit scale. Levels drift toward their true difficulty through
# twin.item_difficulty as people play.
B_EASY = -2.5
B_HARD = 2.5

Mode = Literal["assess", "chill", "balanced", "push"]

TARGET_P: dict[Mode, float] = {
    "assess": 0.65,  # each answer is most informative near 50-70%
    "balanced": 0.80,  # Wilson et al. (2019); Math Garden used 0.75
    "chill": 0.90,
    "push": 0.65,
}

# Above this uncertainty Lodestar measures (Assess) instead of training.
ASSESS_SIGMA = 0.8


def b_for_level(level: float, b_easy: float = B_EASY, b_hard: float = B_HARD) -> float:
    level = min(max(level, 0.0), 1.0)
    return b_easy * (1.0 - level) + b_hard * level


def level_for_b(b: float, b_easy: float = B_EASY, b_hard: float = B_HARD) -> float:
    return min(max((b - b_easy) / (b_hard - b_easy), 0.0), 1.0)


def choose_mode(belief: Belief, success_mode: Literal["chill", "balanced", "push"]) -> Mode:
    return "assess" if belief.sigma > ASSESS_SIGMA else success_mode


def target_b(belief: Belief, target_p: float) -> float:
    """b_next = mu - logit(p*), corrected for uncertainty so predict() hits p* exactly."""
    scale = math.sqrt(1.0 + math.pi * belief.variance / 8.0)
    return belief.mu - logit(target_p) * scale


def next_level(belief: Belief, target_p: float) -> float:
    return level_for_b(target_b(belief, target_p))


def knobs_for(game: Game, level: float) -> dict[str, float]:
    return game.knobs_at(min(max(level, 0.0), 1.0))


def predicted_success(belief: Belief, level: float) -> float:
    return predict(belief, b_for_level(level))
