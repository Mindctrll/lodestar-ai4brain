"""Patterns across a whole profile (docs/plan/07): a skill that has stopped moving, and a profile
split between very strong and very weak skills. Pure; no database access."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean
from typing import Protocol

from backend.scoring.levels import ASSESS_SIGMA

# The blocks of the time-of-day heatmap (start hour, end hour, label).
HOUR_BLOCKS = [(0, 6, "night"), (6, 10, "6-10"), (10, 14, "10-14"), (14, 18, "14-18"),
               (18, 22, "18-22"), (22, 24, "22-24")]  # fmt: skip

# A plateau: at least this many days and answers of practice with no trend either way. Answers are
# noisy, so the test is on means (the later half against the earlier half), with a cap on the
# overall swing. A skill nobody plays isn't stuck, and one near the top has nowhere to go.
PLATEAU_MIN_DAYS = 14
PLATEAU_MIN_ANSWERS = 60
PLATEAU_MAX_DRIFT = 0.08  # logit scale, between the two halves' means
PLATEAU_MAX_SWING = 0.50  # logit scale, top to bottom
PLATEAU_LOOKBACK_DAYS = 45
PLATEAU_RECENT_DAYS = 14
PLATEAU_MAX_PERCENT = 85.0

# A split: one skill near the top and another near the bottom, with ranges that don't overlap, so
# the gap isn't just noise. Most people have a best and a worst skill; this is for the far ends.
SPLIT_STRONG = 90.0
SPLIT_WEAK = 20.0


@dataclass(frozen=True)
class HistoryPoint:
    day: date
    mu: float
    n: int


@dataclass(frozen=True)
class PlateauSpan:
    start: date
    days: int
    answers: int
    swing: float


def find_plateau(points: Sequence[HistoryPoint], today: date) -> PlateauSpan | None:
    """The longest stretch up to the latest day with no trend in the estimate."""
    recent = sorted(
        (p for p in points if p.day >= today - timedelta(days=PLATEAU_LOOKBACK_DAYS)),
        key=lambda p: p.day,
    )
    if len(recent) < 2 or recent[-1].day < today - timedelta(days=PLATEAU_RECENT_DAYS):
        return None
    found = None
    for start in range(len(recent) - 2, -1, -1):
        run = recent[start:]
        mus = [p.mu for p in run]
        swing = max(mus) - min(mus)
        if swing > PLATEAU_MAX_SWING:
            break
        half = len(run) // 2
        drift = abs(fmean(mus[half:]) - fmean(mus[:half]))
        days = (run[-1].day - run[0].day).days
        answers = run[-1].n - run[0].n
        if (
            days >= PLATEAU_MIN_DAYS
            and answers >= PLATEAU_MIN_ANSWERS
            and drift <= PLATEAU_MAX_DRIFT
        ):
            found = PlateauSpan(run[0].day, days, answers, swing)
    return found


class Reading(Protocol):
    @property
    def percent(self) -> float: ...
    @property
    def percent_low(self) -> float: ...
    @property
    def percent_high(self) -> float: ...
    @property
    def sigma(self) -> float: ...


@dataclass(frozen=True)
class Split[R: Reading]:
    strong: R
    weak: R


def find_split[R: Reading](readings: Sequence[R]) -> Split[R] | None:
    """The strongest and weakest measured skills, when they are clearly far apart."""
    sure = [r for r in readings if r.sigma <= ASSESS_SIGMA]
    if len(sure) < 2:
        return None
    strong = max(sure, key=lambda r: r.percent)
    weak = min(sure, key=lambda r: r.percent)
    if strong.percent < SPLIT_STRONG or weak.percent > SPLIT_WEAK:
        return None
    if strong.percent_low <= weak.percent_high:
        return None
    return Split(strong, weak)
