"""Data quality: trust = 0 for random clicking or impossible speed, else 1 (docs/plan/07, 15)."""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# Faster than this is an anticipation, not a response (docs/plan/05).
ANTICIPATION_MS = 150.0

Verdict = Literal["ok", "random_clicking", "impossible_speed", "too_few"]


@dataclass(frozen=True)
class TrialSample:
    correct: bool | None
    rt_ms: float | None


@dataclass(frozen=True)
class QualityReport:
    trust: float
    verdict: Verdict
    anticipations: int
    accuracy: float | None


def _binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def assess_quality(
    trials: Sequence[TrialSample],
    chance: float = 0.5,
    min_trials: int = 8,
) -> QualityReport:
    scored = [t for t in trials if t.correct is not None]
    rts = [t.rt_ms for t in trials if t.rt_ms is not None]
    anticipations = sum(1 for rt in rts if rt < ANTICIPATION_MS)
    if len(scored) < min_trials:
        return QualityReport(1.0, "too_few", anticipations, None)

    hits = sum(1 for t in scored if t.correct)
    accuracy = hits / len(scored)
    median_rt = statistics.median(rts) if rts else None

    # Impossibly fast and nearly always right: not a human playing honestly.
    if median_rt is not None and median_rt < 200.0 and accuracy >= 0.9:
        return QualityReport(0.0, "impossible_speed", anticipations, accuracy)
    # Many anticipations means responses aren't waiting for the stimulus.
    if rts and anticipations / len(rts) > 0.4:
        return QualityReport(0.0, "impossible_speed", anticipations, accuracy)
    # Accuracy indistinguishable from chance, answered quickly: random clicking.
    if (
        _binomial_tail(hits, len(scored), chance) > 0.2
        and median_rt is not None
        and median_rt < 450.0
    ):
        return QualityReport(0.0, "random_clicking", anticipations, accuracy)
    return QualityReport(1.0, "ok", anticipations, accuracy)
