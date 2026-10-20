"""Simulated users with known true skills (docs/plan/15)."""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from backend.registry.models import Registry

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

    def theta(self, dim: str) -> float:
        return self.theta0[dim] + self.learned.get(dim, 0.0)

    def practise(self, dim: str, amount: float) -> None:
        """Power law of practice: each round adds g((n+1)^-a - (n+1+amount)^-a)."""
        n = self.practice.get(dim, 0.0)
        g = self.gain[dim]
        step = g * ((n + 1) ** -self.alpha - (n + 1 + amount) ** -self.alpha)
        self.learned[dim] = self.learned.get(dim, 0.0) + step
        self.practice[dim] = n + amount

    def forget(self, days: float) -> None:
        factor = float(np.exp(-days / FORGETTING_DAYS))
        self.learned = {d: v * factor for d, v in self.learned.items()}


def correlation_matrix(dims: list[str]) -> np.ndarray:
    k = len(dims)
    corr = np.full((k, k), R_OTHER)
    for i, a in enumerate(dims):
        for j, b in enumerate(dims):
            if i == j:
                corr[i, j] = 1.0
            elif a in EXECUTIVE and b in EXECUTIVE:
                corr[i, j] = R_EXECUTIVE
    return corr


def ability_dims(registry: Registry) -> list[str]:
    return [d.id for d in registry.dimensions if not d.style and d.badge != "experimental"]


def make_population(
    registry: Registry,
    n: int,
    rng: np.random.Generator,
    kinds: dict[UserType, float] | None = None,
) -> list[SimUser]:
    dims = ability_dims(registry)
    thetas = rng.multivariate_normal(np.zeros(len(dims)), correlation_matrix(dims), size=n)
    mix = kinds or {"normal": 0.55, "fast_learner": 0.15, "inconsistent": 0.15, "long_gaps": 0.15}
    labels = list(mix)
    probs = np.array([mix[k] for k in labels], dtype=float)
    chosen = rng.choice(len(labels), size=n, p=probs / probs.sum())
    users = []
    for i in range(n):
        kind = labels[chosen[i]]
        gain_scale = 2.0 if kind == "fast_learner" else 1.0
        users.append(
            SimUser(
                user_id=i,
                kind=kind,
                theta0={d: float(thetas[i, j]) for j, d in enumerate(dims)},
                gain={d: float(max(0.0, rng.normal(0.4, 0.15))) * gain_scale for d in dims},
                alpha=float(rng.uniform(0.4, 0.7)),
                lapse=0.02,
                trial_noise=0.6 if kind == "inconsistent" else 0.0,
                fatigue_per_round=0.08 if kind == "frustration_prone" else 0.02,
                device_lag_ms=0.0,
                gap_days=(7, 21) if kind == "long_gaps" else (1, 3),
            )
        )
    return users
