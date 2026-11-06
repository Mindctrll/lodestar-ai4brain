"""Data quality: trust = 0 for random clicking or impossible speed, else 1 (docs/plan/07, 15)."""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# Faster than this is an anticipation, not a response (docs/plan/05).
ANTICIPATION_MS = 150.0
# Button mashing: answers this fast with many errors are flagged even in a short round.
MASHING_MS = 200.0
MASHING_MIN_TRIALS = 5
MASHING_MAX_ACCURACY = 0.7
# Verdicts that mean the answers can't be taken at face value.
FLAGGED: frozenset[str] = frozenset({"random_clicking", "impossible_speed"})

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
    median_rt_ms: float | None = None


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
    median_rt = statistics.median(rts) if rts else None
    hits = sum(1 for t in scored if t.correct)
    accuracy = hits / len(scored) if scored else None
    if (
        accuracy is not None
        and median_rt is not None
        and len(scored) >= MASHING_MIN_TRIALS
        and median_rt < MASHING_MS
        and accuracy < MASHING_MAX_ACCURACY
    ):
        return QualityReport(0.0, "random_clicking", anticipations, accuracy, median_rt)
    if len(scored) < min_trials or accuracy is None:
        return QualityReport(1.0, "too_few", anticipations, None, median_rt)

    # Impossibly fast and nearly always right: not a human playing honestly.
    if median_rt is not None and median_rt < 200.0 and accuracy >= 0.9:
        return QualityReport(0.0, "impossible_speed", anticipations, accuracy, median_rt)
    # Many anticipations means responses aren't waiting for the stimulus.
    if rts and anticipations / len(rts) > 0.4:
        return QualityReport(0.0, "impossible_speed", anticipations, accuracy, median_rt)
    # Accuracy indistinguishable from chance, answered quickly: random clicking.
    if (
        _binomial_tail(hits, len(scored), chance) > 0.2
        and median_rt is not None
        and median_rt < 450.0
    ):
        return QualityReport(0.0, "random_clicking", anticipations, accuracy, median_rt)
    return QualityReport(1.0, "ok", anticipations, accuracy, median_rt)


# Device lag (docs/plan/06, Quick Draw): a slow screen or input adds a constant delay to every
# response time. At onboarding and check-ups Quick Draw starts with "tap in time": the user taps
# along with a flashing star, and each tap's offset from its flash is that delay plus a little
# human timing noise. Like a rhythm game's calibration, the median offset estimates it.
TAP_IN_TIME = "tap_in_time"
MIN_TAPS = 5
MAX_LAG_MS = 250.0


def device_lag(offsets_ms: Sequence[float]) -> float:
    """Device lag in ms from tap-in-time offsets: their median, clamped to 0..250; 0 when there
    are too few taps to tell."""
    if len(offsets_ms) < MIN_TAPS:
        return 0.0
    return min(max(statistics.median(offsets_ms), 0.0), MAX_LAG_MS)
