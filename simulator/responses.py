"""How a simulated user answers one trial (docs/plan/15): P(correct) = logistic(theta - b), with a
response time that falls as skill rises. Special user types bend these rules."""

import math
from dataclasses import dataclass

import numpy as np

from backend.registry.models import Game
from backend.scoring.kalman_elo import logistic
from simulator.population import SimUser

BASE_RT_MS = 900.0


@dataclass(frozen=True)
class SimAnswer:
    correct: bool
    rt_ms: float


def answer(
    user: SimUser,
    game: Game,
    primary_dim: str,
    b: float,
    deadline_ms: float | None,
    fatigue: float,
    rng: np.random.Generator,
) -> SimAnswer:
    if user.kind == "cheater":
        return SimAnswer(True, float(rng.uniform(60, 140)))
    if user.kind == "random_clicker":
        return SimAnswer(bool(rng.random() < 0.5), float(rng.uniform(160, 380)))

    theta = user.theta(primary_dim) - fatigue
    if user.trial_noise:
        theta += float(rng.normal(0, user.trial_noise))
    p = logistic(theta - b)
    if rng.random() < user.lapse:
        return SimAnswer(bool(rng.random() < 0.5), float(rng.uniform(250, 1200)))

    if deadline_ms:
        # Timed games measure pace: answers are almost always right, and ability shows as
        # answering within the on-pace window (half the deadline) that the rescaled
        # high-speed-high-stakes score rewards, so P(on pace) = logistic(theta - b).
        correct = bool(rng.random() < 0.95)
        on_pace = rng.random() < p
        share = rng.uniform(0.2, 0.48) if on_pace else rng.uniform(0.52, 0.97)
        rt = max(180.0, share * deadline_ms)
        return SimAnswer(correct, rt + user.device_lag_ms)

    correct = bool(rng.random() < p)
    rt = BASE_RT_MS * math.exp(-0.15 * theta + float(rng.normal(0, 0.3)))
    return SimAnswer(correct, max(rt, 160.0) + user.device_lag_ms)
