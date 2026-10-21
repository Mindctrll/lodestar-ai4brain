"""AI Collaboration Score (docs/plan/11). Pure functions.

Each component is a Beta posterior with a Beta(2, 2) prior, s_k = (successes + 2) / (opportunities
+ 4). ACS = 100 x sum_k w_k s_k. A component with fewer than 5 opportunities shows "not enough
data" and its weight is spread proportionally over the others. The range comes from Monte Carlo
draws from the posteriors (80% interval).
"""

from dataclasses import dataclass

import numpy as np

from backend.contracts.acs import ACS_COMPONENT_NAMES, AcsComponent

# Design hypothesis, justified in docs/plan/11 (brief proposed V25 A20 I20 C20 R15).
WEIGHTS: dict[AcsComponent, float] = {"V": 0.30, "A": 0.20, "I": 0.20, "C": 0.15, "R": 0.15}
PRIOR = 2.0
MIN_OPPORTUNITIES = 5
DRAWS = 1000
INTERVAL = (10.0, 90.0)  # percentiles: an 80% range


@dataclass(frozen=True)
class ComponentScore:
    code: AcsComponent
    name: str
    successes: int
    opportunities: int
    mean: float
    low: float
    high: float
    weight: float  # effective weight after redistribution; 0 when there isn't enough data

    @property
    def enough(self) -> bool:
        return self.opportunities >= MIN_OPPORTUNITIES


@dataclass(frozen=True)
class AcsScore:
    value: float | None  # 0-100, None until some component has enough data
    low: float | None
    high: float | None
    components: list[ComponentScore]


def effective_weights(
    counts: dict[AcsComponent, tuple[int, int]], weights: dict[AcsComponent, float] = WEIGHTS
) -> dict[AcsComponent, float]:
    usable = {k: w for k, w in weights.items() if counts.get(k, (0, 0))[1] >= MIN_OPPORTUNITIES}
    total = sum(usable.values())
    return {k: (usable.get(k, 0.0) / total if total else 0.0) for k in weights}


def score(
    counts: dict[AcsComponent, tuple[int, int]],
    weights: dict[AcsComponent, float] = WEIGHTS,
    seed: int = 0,
) -> AcsScore:
    """`counts` maps a component to (successes, opportunities)."""
    rng = np.random.default_rng(seed)
    eff = effective_weights(counts, weights)
    components = []
    draws = np.zeros(DRAWS)
    for code in weights:
        successes, opportunities = counts.get(code, (0, 0))
        a, b = successes + PRIOR, opportunities - successes + PRIOR
        sample = rng.beta(a, b, DRAWS)
        lo, hi = np.percentile(sample, INTERVAL)
        components.append(
            ComponentScore(
                code=code,
                name=ACS_COMPONENT_NAMES[code],
                successes=successes,
                opportunities=opportunities,
                mean=a / (a + b),
                low=float(lo),
                high=float(hi),
                weight=eff[code],
            )
        )
        draws += eff[code] * sample
    if not any(c.enough for c in components):
        return AcsScore(None, None, None, components)
    value = 100 * sum(c.weight * c.mean for c in components)
    lo, hi = np.percentile(100 * draws, INTERVAL)
    return AcsScore(float(value), float(lo), float(hi), components)
