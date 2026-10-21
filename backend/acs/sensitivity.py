"""Experiment 7 (docs/plan/15): are ACS rankings stable when the weights move by +/-5 points?

Simulated users get hidden per-component success rates and realistic opportunity counts; we rank
them under the chosen weights and under every single-component +/-5 shift (renormalised), and
report the worst Spearman rank correlation.
"""

from dataclasses import dataclass

import numpy as np

from backend.acs.score import WEIGHTS, score
from backend.contracts.acs import AcsComponent

OPPORTUNITIES: dict[AcsComponent, tuple[int, int]] = {
    "V": (15, 40),
    "A": (20, 60),
    "I": (5, 15),
    "C": (5, 12),
    "R": (5, 10),
}


@dataclass(frozen=True)
class Sensitivity:
    worst_rho: float
    shifts: dict[str, float]


def _rank(values: np.ndarray) -> np.ndarray:
    order = values.argsort()
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(len(values))
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(_rank(a), _rank(b))[0, 1])


def simulate_counts(n: int, rng: np.random.Generator) -> list[dict[AcsComponent, tuple[int, int]]]:
    users = []
    ability = rng.normal(0, 1, n)  # a shared "works well with AI" tendency
    for i in range(n):
        counts: dict[AcsComponent, tuple[int, int]] = {}
        for code, (lo, hi) in OPPORTUNITIES.items():
            p = 1 / (1 + np.exp(-(0.6 * ability[i] + rng.normal(0, 0.8))))
            opp = int(rng.integers(lo, hi + 1))
            counts[code] = (int(rng.binomial(opp, p)), opp)
        users.append(counts)
    return users


def analyse(n: int = 200, seed: int = 0) -> Sensitivity:
    rng = np.random.default_rng(seed)
    users = simulate_counts(n, rng)

    def values(weights: dict[AcsComponent, float]) -> np.ndarray:
        return np.array([score(u, weights).value or 0.0 for u in users])

    base = values(WEIGHTS)
    shifts: dict[str, float] = {}
    for code in WEIGHTS:
        for delta in (-0.05, 0.05):
            w = dict(WEIGHTS)
            w[code] = max(0.0, w[code] + delta)
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            shifts[f"{code}{delta:+.2f}"] = spearman(base, values(w))
    return Sensitivity(min(shifts.values()), shifts)
