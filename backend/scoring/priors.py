"""Cold-start priors (docs/plan/07, 10): a skill never played yet starts from what correlated,
already measured skills suggest, instead of the population middle.

Skills are treated as jointly normal on the population scale with the NCPT correlations
(registry/priors.yaml). Each measured estimate is a noisy reading of its skill (variance sigma^2),
so a vague estimate moves the prior less. The prior mean is the conditional mean; its spread is
SIGMA_START times the conditional standard deviation, so it stays wide.
"""

from collections.abc import Mapping

import numpy as np

from backend.registry.models import SkillPriors
from backend.scoring.kalman_elo import SIGMA_START, Belief

MIN_MEASURED_N = 1


def correlation(priors: SkillPriors | None, a: str, b: str, default: float = 0.0) -> float:
    if a == b:
        return 1.0
    if priors is None:
        return default
    return priors.pairs().get(frozenset((a, b)), default)


def nearest_correlation(m: np.ndarray, floor: float = 1e-3) -> np.ndarray:
    """Clip negative eigenvalues so a matrix filled from pairs is a valid correlation matrix."""
    values, vectors = np.linalg.eigh((m + m.T) / 2)
    fixed = vectors @ np.diag(np.maximum(values, floor)) @ vectors.T
    d = np.sqrt(np.diag(fixed))
    return np.asarray(fixed / np.outer(d, d))


def cold_start(dim: str, known: Mapping[str, Belief], priors: SkillPriors | None) -> Belief:
    """The starting belief for `dim`, given the user's measured skills."""
    if priors is None or dim not in priors.subtests:
        return Belief()
    measured = [
        (d, b) for d, b in known.items()
        if d != dim and b.n >= MIN_MEASURED_N and d in priors.subtests
        and frozenset((d, dim)) in priors.pairs()
    ]  # fmt: skip
    if not measured:
        return Belief()
    names = [d for d, _ in measured]
    r = np.array([correlation(priors, dim, d) for d in names])
    rmm = nearest_correlation(np.array([[correlation(priors, a, b) for b in names] for a in names]))
    noise = np.diag([b.sigma**2 for _, b in measured])
    mu = np.array([b.mu for _, b in measured])
    weights = np.linalg.solve(rmm + noise, r)
    mean = float(weights @ mu)
    var = float(max(1.0 - weights @ r, 0.05))
    return Belief(mu=mean, sigma=SIGMA_START * var**0.5)
