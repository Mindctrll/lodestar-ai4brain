"""From skill estimates to percentages (docs/plan/07). Every percentage comes with its range.

WP2.7 replaces the simulated norms with NCPT-derived ones where a dimension maps to an NCPT
subtest; the UI labels simulated norms as such.
"""

import math
from dataclasses import dataclass
from typing import Literal

from backend.scoring.kalman_elo import Belief, interval


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class Norm:
    mean: float = 0.0
    sd: float = 1.0
    source: Literal["simulated", "ncpt"] = "simulated"


@dataclass(frozen=True)
class PercentRange:
    value: float  # 0..100
    low: float
    high: float
    source: Literal["simulated", "ncpt"]

    def label(self) -> str:
        return f"{self.value:.0f}% (likely {self.low:.0f}-{self.high:.0f}%)"


class Norms:
    def __init__(self, norms: dict[str, Norm] | None = None) -> None:
        self._norms = norms or {}

    def norm(self, dim: str) -> Norm:
        return self._norms.get(dim, Norm())

    def percentile(self, dim: str, belief: Belief) -> PercentRange:
        norm = self.norm(dim)
        lo, hi = interval(belief)

        def pct(x: float) -> float:
            return 100.0 * normal_cdf((x - norm.mean) / norm.sd)

        return PercentRange(pct(belief.mu), pct(lo), pct(hi), norm.source)
