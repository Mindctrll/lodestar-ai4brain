"""Simulated users with known true skills (docs/plan/15)."""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from backend.registry.models import Registry, SkillPriors
from backend.scoring.priors import nearest_correlation

UserType = Literal[
    "normal",
    "fast_learner",
    "inconsistent",
    "long_gaps",
    "quitter",
    "random_clicker",
    "cheater",
    "frustration_prone",
]

# Executive functions correlate more strongly with each other (docs/plan/15).
EXECUTIVE = {"inhibition", "working_memory", "cognitive_flexibility", "selective_attention"}
R_EXECUTIVE = 0.45
R_OTHER = 0.30

FORGETTING_DAYS = 45.0  # learned gains fade with this time constant during gaps


@dataclass
class SimUser:
    user_id: int
    kind: UserType
    theta0: dict[str, float]
    gain: dict[str, float]
    alpha: float
    lapse: float
    trial_noise: float
    fatigue_per_round: float
    device_lag_ms: float
    gap_days: tuple[int, int]
    learned: dict[str, float] = field(default_factory=dict)
    practice: dict[str, float] = field(default_factory=dict)
    rate: tuple[float, float] | None = None  # (a, b) of the Lumosity per-round gain
    game_gain: dict[str, float] = field(default_factory=dict)  # hidden per-game learning rates

    def theta(self, dim: str) -> float:
        return self.theta0[dim] + self.learned.get(dim, 0.0)

    def practise(self, dim: str, amount: float, game_id: str | None = None) -> None:
        """Power law of practice. With the Lumosity rate (registry/practice.yaml) a round adds
        g * amount * a * (n+1)^-b, where g is this person's learning factor; without it, the
        older form g((n+1)^-alpha - (n+1+amount)^-alpha). Some games suit a person better
        than others: `game_gain` scales the step (1 when not set)."""
        n = self.practice.get(dim, 0.0)
        g = self.gain[dim] * (self.game_gain.get(game_id, 1.0) if game_id else 1.0)
        if self.rate is not None:
            a, b = self.rate
            step = g * amount * a * (n + 1) ** -b
        else:
            step = g * ((n + 1) ** -self.alpha - (n + 1 + amount) ** -self.alpha)
        self.learned[dim] = self.learned.get(dim, 0.0) + step
        self.practice[dim] = n + amount

    def forget(self, days: float) -> None:
        factor = float(np.exp(-days / FORGETTING_DAYS))
        self.learned = {d: v * factor for d, v in self.learned.items()}


def correlation_matrix(dims: list[str], priors: SkillPriors | None = None) -> np.ndarray:
    """NCPT correlations where a pair was measured (registry/priors.yaml), else the defaults
    above; repaired to a valid correlation matrix."""
    k = len(dims)
    corr = np.full((k, k), R_OTHER)
    pairs = priors.pairs() if priors is not None else {}
    for i, a in enumerate(dims):
        for j, b in enumerate(dims):
            if i == j:
                corr[i, j] = 1.0
            elif frozenset((a, b)) in pairs:
                corr[i, j] = pairs[frozenset((a, b))]
            elif a in EXECUTIVE and b in EXECUTIVE:
                corr[i, j] = R_EXECUTIVE
    return nearest_correlation(corr)


def ability_dims(registry: Registry) -> list[str]:
    return [d.id for d in registry.dimensions if not d.style and d.badge != "experimental"]


def make_population(
    registry: Registry,
    n: int,
    rng: np.random.Generator,
    kinds: dict[UserType, float] | None = None,
) -> list[SimUser]:
    dims = ability_dims(registry)
    thetas = rng.multivariate_normal(
        np.zeros(len(dims)), correlation_matrix(dims, registry.priors), size=n
    )
    mix = kinds or {"normal": 0.55, "fast_learner": 0.15, "inconsistent": 0.15, "long_gaps": 0.15}
    labels = list(mix)
    probs = np.array([mix[k] for k in labels], dtype=float)
    chosen = rng.choice(len(labels), size=n, p=probs / probs.sum())
    users = []
    rate = (
        (registry.practice.per_round.a, registry.practice.per_round.b)
        if registry.practice is not None
        else None
    )
    for i in range(n):
        kind = labels[chosen[i]]
        gain_scale = 2.0 if kind == "fast_learner" else 1.0
        # With the Lumosity rate, gain is a personal factor around 1 (fast learners 1.6x).
        mean, sd = (1.0, 0.35) if rate else (0.4, 0.15)
        if rate and kind == "fast_learner":
            gain_scale = 1.6
        users.append(
            SimUser(
                user_id=i,
                kind=kind,
                theta0={d: float(thetas[i, j]) for j, d in enumerate(dims)},
                gain={d: float(max(0.0, rng.normal(mean, sd))) * gain_scale for d in dims},
                alpha=float(rng.uniform(0.4, 0.7)),
                lapse=0.02,
                trial_noise=0.6 if kind == "inconsistent" else 0.0,
                fatigue_per_round=0.08 if kind == "frustration_prone" else 0.02,
                device_lag_ms=0.0,
                gap_days=(7, 21) if kind == "long_gaps" else (1, 3),
                rate=rate,
            )
        )
    return users
