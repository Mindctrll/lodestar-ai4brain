"""Evaluation experiments 1-5 from docs/plan/15 on simulated runs."""

from dataclasses import dataclass

import numpy as np

from backend.registry.models import Registry
from backend.scoring.kalman_elo import interval
from simulator.run import UserRun

Z80 = 1.2816


def established_tracked(registry: Registry, runs: list[UserRun]) -> list[str]:
    """Established skills that the simulated sessions actually practise."""
    practised = {d for r in runs for d, b in r.snapshots[-1].beliefs.items() if b.n > 0}
    return [
        d.id
        for d in registry.dimensions
        if d.badge == "established" and d.id in practised and d.id in runs[0].user.theta0
    ]


@dataclass(frozen=True)
class Recovery:
    session: int
    r_by_dim: dict[str, float]
    rmse_by_dim: dict[str, float]
    practised_share: dict[str, float]

    @property
    def mean_r(self) -> float:
        return float(np.mean(list(self.r_by_dim.values())))


def recovery(runs: list[UserRun], dims: list[str], session: int) -> Recovery:
    r_by, rmse_by, share = {}, {}, {}
    for dim in dims:
        mus, truths = [], []
        for run in runs:
            snap = run.snapshots[session - 1]
            if snap.beliefs[dim].n > 0:
                mus.append(snap.beliefs[dim].mu)
                truths.append(snap.truth[dim])
        share[dim] = len(mus) / len(runs)
        if len(mus) >= 3:
            r_by[dim] = float(np.corrcoef(mus, truths)[0, 1])
            rmse_by[dim] = float(np.sqrt(np.mean((np.array(mus) - np.array(truths)) ** 2)))
    return Recovery(session, r_by, rmse_by, share)


def coverage(runs: list[UserRun], dims: list[str], sessions: list[int]) -> float:
    inside = total = 0
    for run in runs:
        for s in sessions:
            snap = run.snapshots[s - 1]
            for dim in dims:
                belief = snap.beliefs[dim]
                if belief.n == 0:
                    continue
                lo, hi = interval(belief, Z80)
                inside += lo <= snap.truth[dim] <= hi
                total += 1
    return inside / total if total else float("nan")


@dataclass(frozen=True)
class Success:
    overall: float
    by_tertile: list[float]
    rounds: int


def success_rate(runs: list[UserRun], mode: str = "balanced") -> Success:
    per_user: list[tuple[float, float]] = []
    scores: list[float] = []
    for run in runs:
        own = [r.mean_score for r in run.rounds if r.mode == mode and r.mean_score is not None]
        scores.extend(own)
        if own:
            ability = float(np.mean(list(run.user.theta0.values())))
            per_user.append((ability, float(np.mean(own))))
    per_user.sort()
    thirds = np.array_split(np.array([s for _, s in per_user]), 3)
    return Success(float(np.mean(scores)), [float(np.mean(t)) for t in thirds], len(scores))


def onboarding_sigma(runs: list[UserRun], core: set[str]) -> dict[str, float]:
    return {d: float(np.mean([run.snapshots[0].beliefs[d].sigma for run in runs])) for d in core}


@dataclass(frozen=True)
class Detection:
    precision: float
    recall: float


def bad_data_detection(runs: list[UserRun]) -> Detection:
    """A user is flagged when at least half of their rounds got trust 0."""
    tp = fp = fn = 0
    for run in runs:
        bad = run.user.kind in {"random_clicker", "cheater"}
        flagged = run.trust_zero_rounds >= max(1, len(run.rounds) // 2)
        tp += bad and flagged
        fp += (not bad) and flagged
        fn += bad and not flagged
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return Detection(precision, recall)
