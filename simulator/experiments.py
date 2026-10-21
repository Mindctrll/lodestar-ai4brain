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


def coverage(runs: list[UserRun], dims: list[str], sessions: list[int], z: float = Z80) -> float:
    """Share of ranges containing the true skill (the 80% range by default)."""
    inside = total = 0
    for run in runs:
        for s in sessions:
            snap = run.snapshots[s - 1]
            for dim in dims:
                belief = snap.beliefs[dim]
                if belief.n == 0:
                    continue
                lo, hi = interval(belief, z)
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


def flagged(run: UserRun) -> bool:
    """A user is flagged when at least half of their rounds got trust 0."""
    return run.trust_zero_rounds >= max(1, len(run.rounds) // 2)


def bad_data_detection(runs: list[UserRun]) -> Detection:
    tp = fp = fn = 0
    for run in runs:
        bad = run.user.kind in {"random_clicker", "cheater"}
        is_flagged = flagged(run)
        tp += bad and is_flagged
        fp += (not bad) and is_flagged
        fn += bad and not is_flagged
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return Detection(precision, recall)


# docs/plan/15 targets.
MIN_R_AT_3 = 0.8
COVERAGE_RANGE = (0.75, 0.85)
SUCCESS_TARGET, SUCCESS_TOL = 0.80, 0.05
ONBOARDING_SIGMA_MAX = 0.8
DETECTION_MIN = (0.9, 0.8)  # precision, recall


@dataclass(frozen=True)
class Gate:
    dims: list[str]
    recovery: dict[int, Recovery]
    success: Success
    checks: list[tuple[str, str, str, bool]]  # experiment, result, target, pass

    @property
    def passed(self) -> bool:
        return all(ok for *_, ok in self.checks)


def gate(runs: list[UserRun], bad_runs: list[UserRun], registry: Registry) -> Gate:
    """Experiments 1-5 of docs/plan/15 against their targets (the offline simulator and the
    simulator through the real graph use the same definitions)."""
    dims = established_tracked(registry, runs)
    rec = {
        s: recovery(runs, dims, s) for s in (1, 3, 10) if all(len(r.snapshots) >= s for r in runs)
    }
    cov = coverage(runs, dims, [s for s in (3, 10) if s in rec])
    succ = success_rate(runs)
    onboard = onboarding_sigma(runs, registry.core_skills())
    det = bad_data_detection(bad_runs)
    checks = [
        (f"1. Recovery r after 3 sessions (mean over {len(dims)} established skills)",
         f"{rec[3].mean_r:.3f}", f"> {MIN_R_AT_3}", rec[3].mean_r > MIN_R_AT_3),
        ("2. 80% ranges containing the true skill (sessions 3 and 10)",
         f"{cov:.3f}", f"{COVERAGE_RANGE[0]}-{COVERAGE_RANGE[1]}",
         COVERAGE_RANGE[0] <= cov <= COVERAGE_RANGE[1]),
        ("3. Achieved success in Balanced mode", f"{succ.overall:.3f}",
         f"{SUCCESS_TARGET} +/- {SUCCESS_TOL}", abs(succ.overall - SUCCESS_TARGET) <= SUCCESS_TOL),
        ("4. Mean sigma after onboarding, worst core skill", f"{max(onboard.values()):.3f}",
         f"< {ONBOARDING_SIGMA_MAX}", max(onboard.values()) < ONBOARDING_SIGMA_MAX),
        ("5. Bad-data detection precision / recall", f"{det.precision:.2f} / {det.recall:.2f}",
         f"> {DETECTION_MIN[0]} / > {DETECTION_MIN[1]}",
         det.precision > DETECTION_MIN[0] and det.recall > DETECTION_MIN[1]),
    ]  # fmt: skip
    return Gate(dims, rec, succ, checks)
