"""Kalman-Elo: a score and an honest uncertainty per skill (docs/plan/07). Pure functions.

Each skill is a belief theta ~ Normal(mu, sigma^2) on a logit scale; each level has a difficulty b.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime

SIGMA_START = 1.5
MU_START = 0.0
# Staleness drift per day without practice (sigma grows noticeably after about 3 weeks).
Q_PER_DAY = 0.002
# Process noise added before each round: answers within a session aren't independent.
Q_ROUND = 0.035
# Item difficulties only learn from users whose skill is already well known.
ITEM_LEARNING_SIGMA_MAX = 0.6
ITEM_LEARNING_RATE = 0.02


@dataclass(frozen=True)
class Belief:
    mu: float = MU_START
    sigma: float = SIGMA_START
    n: int = 0
    last_practised: datetime | None = None

    @property
    def variance(self) -> float:
        return self.sigma * self.sigma


def logistic(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1.0 - p))


def predict(belief: Belief, b: float) -> float:
    """Predicted success, widened for uncertainty: logistic((mu - b) / sqrt(1 + pi sigma^2 / 8))."""
    return logistic((belief.mu - b) / math.sqrt(1.0 + math.pi * belief.variance / 8.0))


def update(belief: Belief, b: float, score: float, weight: float) -> Belief:
    """One Laplace step for a logistic observation with weight w (loading x reliability x context
    x trust). Uncertainty never grows from an answer; the mean moves toward the evidence."""
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    if weight < 0.0:
        raise ValueError(f"weight must be >= 0, got {weight}")
    if weight == 0.0:
        return belief
    p = predict(belief, b)
    info = p * (1.0 - p)
    variance = 1.0 / (1.0 / belief.variance + weight * info)
    mu = belief.mu + variance * weight * (score - p)
    return replace(belief, mu=mu, sigma=math.sqrt(variance), n=belief.n + 1)


def drift(
    belief: Belief,
    now: datetime,
    q_per_day: float = Q_PER_DAY,
    sigma_start: float = SIGMA_START,
) -> Belief:
    """Staleness drift: uncertainty grows with time away, capped at the starting uncertainty."""
    if belief.last_practised is None:
        return belief
    days = max(0.0, (now - belief.last_practised).total_seconds() / 86_400)
    variance = min(sigma_start**2, belief.variance + q_per_day * days)
    return replace(belief, sigma=math.sqrt(max(variance, belief.variance)))


def add_process_noise(
    belief: Belief, q_round: float = Q_ROUND, sigma_start: float = SIGMA_START
) -> Belief:
    variance = min(sigma_start**2, belief.variance + q_round)
    return replace(belief, sigma=math.sqrt(max(variance, belief.variance)))


def update_item_difficulty(b: float, score: float, p: float, learner_sigma: float) -> float:
    """b' = b - 0.02 (S - p), only from learners we already know well."""
    if learner_sigma >= ITEM_LEARNING_SIGMA_MAX:
        return b
    return b - ITEM_LEARNING_RATE * (score - p)


def interval(belief: Belief, z: float = 1.2816) -> tuple[float, float]:
    """80% interval for theta by default (mu +/- 1.28 sigma)."""
    return belief.mu - z * belief.sigma, belief.mu + z * belief.sigma
