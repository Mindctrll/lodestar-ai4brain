"""Engagement risk (docs/plan/10, section 2): the chance someone takes a week off, as a range.

Only behaviour features that exist both in OULAD and in Najma (no demographics, for fairness):
days since last activity, active days in the last 7, the 7 before and the last 28, the trend in
activity per active day, the current streak, recent failures and days since starting. The same
`feature_row` builds a training row from OULAD's daily clicks and a serving row from Najma's
daily rounds, so the two can't drift apart.

The probability comes with an inductive Venn-Abers range [p0, p1]: two isotonic calibrations on
held-out students, one assuming the new case is a 0 and one assuming it's a 1. The range is
well calibrated by construction, so the app never shows a single made-up number (AGENTS.md
rule 5).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

FEATURES = (
    "days_since_last",
    "active_7",
    "active_prev_7",
    "active_28",
    "volume_trend",
    "streak",
    "fails_28",
    "tenure",
)
HORIZON_DAYS = 7
CAPS = {"days_since_last": 60.0, "streak": 28.0, "fails_28": 5.0, "tenure": 180.0}


def feature_row(volume: np.ndarray, fails: np.ndarray, t: int) -> list[float]:
    """Features on day index `t` (inclusive) from daily activity `volume` (clicks in OULAD,
    rounds in Najma) and daily `fails` (failed assessments, rounds that went badly)."""
    seen = volume[: t + 1]
    active = np.flatnonzero(seen > 0)
    last = int(active[-1]) if len(active) else None
    first = int(active[0]) if len(active) else None

    def days_active(lo: int, hi: int) -> int:  # day indexes lo..hi inclusive
        return int(np.count_nonzero(seen[max(0, lo) : hi + 1] > 0))

    def per_active_day(lo: int, hi: int) -> float | None:
        window = seen[max(0, lo) : hi + 1]
        on = window[window > 0]
        return float(on.mean()) if len(on) else None

    recent, before = per_active_day(t - 6, t), per_active_day(t - 13, t - 7)
    trend = math.log(recent / before) if recent and before else 0.0
    streak = 0
    while t - streak >= 0 and seen[t - streak] > 0:
        streak += 1
    row = {
        "days_since_last": float(t - last) if last is not None else CAPS["days_since_last"],
        "active_7": float(days_active(t - 6, t)),
        "active_prev_7": float(days_active(t - 13, t - 7)),
        "active_28": float(days_active(t - 27, t)),
        "volume_trend": float(np.clip(trend, -3.0, 3.0)),
        "streak": float(streak),
        "fails_28": float(fails[max(0, t - 27) : t + 1].sum()),
        "tenure": float(t - first) if first is not None else 0.0,
    }
    return [min(row[f], CAPS[f]) if f in CAPS else row[f] for f in FEATURES]


# Venn-Abers -----------------------------------------------------------------------------------


def _isotonic_at(x: np.ndarray, y: np.ndarray, at: float) -> float:
    from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(x, y)
    return float(iso.predict(np.array([at]))[0])


def venn_abers_grid(
    scores: np.ndarray, labels: np.ndarray, points: int = 200
) -> tuple[list[float], list[float], list[float]]:
    """p0 and p1 on a grid of scores (the calibration scores' quantiles); between grid points
    they are interpolated, which is close because both are monotone step functions."""
    grid = np.unique(np.quantile(scores, np.linspace(0.0, 1.0, points)))
    p0 = [_isotonic_at(np.append(scores, s), np.append(labels, 0.0), s) for s in grid]
    p1 = [_isotonic_at(np.append(scores, s), np.append(labels, 1.0), s) for s in grid]
    return grid.tolist(), p0, p1


@dataclass(frozen=True)
class Risk:
    low: float  # p0
    high: float  # p1
    p: float  # the merged point, p1 / (1 - p0 + p1), used only for ranking and metrics

    @property
    def high_risk(self) -> bool:
        """Sure enough to act on: even the low end of the range says likely."""
        return self.low >= 0.5


def venn_abers(
    score: float, grid: Sequence[float], p0: Sequence[float], p1: Sequence[float]
) -> Risk:
    lo = float(np.interp(score, grid, p0))
    hi = float(np.interp(score, grid, p1))
    lo, hi = min(lo, hi), max(lo, hi)
    return Risk(lo, hi, hi / (1.0 - lo + hi))


# The scorer -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class EngagementModel:
    """Standardised logistic regression plus its Venn-Abers grid; small enough to live in
    agent.ml_models.metrics, so serving needs no model file."""

    version: str
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    grid: list[float]
    p0: list[float]
    p1: list[float]

    def score(self, row: Sequence[float]) -> float:
        z = (np.asarray(row) - np.asarray(self.mean)) / np.asarray(self.scale)
        return float(z @ np.asarray(self.coef) + self.intercept)

    def risk(self, row: Sequence[float]) -> Risk:
        return venn_abers(self.score(row), self.grid, self.p0, self.p1)

    @classmethod
    def from_metrics(cls, version: str, metrics: dict[str, Any]) -> EngagementModel:
        m = metrics["serving"]
        return cls(
            version=version,
            mean=m["mean"],
            scale=m["scale"],
            coef=m["coef"],
            intercept=m["intercept"],
            grid=m["grid"],
            p0=m["p0"],
            p1=m["p1"],
        )
