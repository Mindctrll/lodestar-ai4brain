"""Play simulated users through sessions with the real scoring engine (WP1.2: no graph yet).

The game choice stands in for `plan_next` until WP2.3: the least certain skill, a different game
than last time, and the level that targets the mode's success rate.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np

from backend.contracts.trial import TrialEvent
from backend.registry.models import Game, PracticeGain, Registry, SkillPriors
from backend.scoring.kalman_elo import Belief, drift
from backend.scoring.levels import TARGET_P, b_for_level, choose_mode, next_level
from backend.scoring.loadings import loading_matrix
from backend.scoring.priors import cold_start
from backend.scoring.rounds import score_round
from simulator.population import SimUser
from simulator.responses import answer

TRIALS_PER_ROUND = 12
ONBOARDING_TRIALS = 10
ROUNDS_PER_SESSION = 3
START = datetime(2026, 9, 1, 19, 0, tzinfo=UTC)


@dataclass
class RoundLog:
    session: int
    game_id: str
    mode: str
    target_p: float
    mean_score: float | None
    accuracy: float
    gain: float = 0.0  # change in the estimate of the game's main skill (the bandit's reward)


@dataclass
class Snapshot:
    session: int
    beliefs: dict[str, Belief]
    truth: dict[str, float]


@dataclass
class UserRun:
    user: SimUser
    beliefs: dict[str, Belief]
    rounds: list[RoundLog] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    trust_zero_rounds: int = 0


def _p1_games_by_dim(registry: Registry) -> dict[str, list[Game]]:
    out: dict[str, list[Game]] = {}
    for game in registry.games:
        if game.phase == "P1" and game.kind == "game":
            for dim in game.primary_dims:
                out.setdefault(dim, []).append(game)
    return out


def play_round(
    run: UserRun,
    game: Game,
    mode: str,
    target_p: float,
    level: float,
    n_trials: int,
    session: int,
    now: datetime,
    fatigue: float,
    loadings: dict[str, float],
    rng: np.random.Generator,
    priors: SkillPriors | None = None,
    practice: PracticeGain | None = None,
) -> None:
    user = run.user
    primary = max(game.dims, key=lambda d: game.dims[d])
    b = b_for_level(level)
    deadline = game.knobs["deadline_ms"].at(level) if "deadline_ms" in game.knobs else None
    if game.scoring != "hshs":
        deadline = None
    round_id: UUID = uuid4()
    session_id: UUID = uuid4()
    trials = []
    for i in range(n_trials):
        a = answer(user, game, primary, b, deadline, fatigue, rng)
        stimulus = {"deadline_ms": deadline} if deadline else {}
        trials.append(
            TrialEvent(
                trial_id=uuid4(),
                round_id=round_id,
                session_id=session_id,
                game_id=game.id,
                level=level,
                trial_index=i,
                stimulus=stimulus,
                correct=a.correct,
                rt_ms=a.rt_ms,
                ts=now + timedelta(seconds=5 * i),
            )
        )
    # Same cold-start priors as the app (backend/scoring/priors.py).
    beliefs = {
        d: run.beliefs[d] if run.beliefs[d].n > 0 else cold_start(d, run.beliefs, priors)
        for d in loadings
    }
    outcome = score_round(
        game, trials, beliefs, loadings, practice=practice.per_round if practice else None
    )
    before = beliefs[primary].mu if primary in beliefs else 0.0
    run.beliefs.update(outcome.beliefs)
    if outcome.quality.trust == 0:
        run.trust_zero_rounds += 1
    accuracy = sum(t.correct is True for t in trials) / len(trials)
    gain = run.beliefs[primary].mu - before if primary in run.beliefs else 0.0
    run.rounds.append(
        RoundLog(session, game.id, mode, target_p, outcome.mean_score, accuracy, gain)
    )
    for dim, loading in loadings.items():
        if dim in user.gain:
            user.practise(dim, loading, game.id)


ChooseGame = Callable[[list[Game], UserRun, np.random.Generator], Game]


def random_game(options: list[Game], run: UserRun, rng: np.random.Generator) -> Game:
    return options[int(rng.integers(len(options)))]


def simulate_user(
    user: SimUser,
    registry: Registry,
    sessions: int,
    rng: np.random.Generator,
    success_mode: str = "balanced",
    choose_game: ChooseGame = random_game,
) -> UserRun:
    matrix = loading_matrix(registry)
    by_dim = _p1_games_by_dim(registry)
    tracked = sorted(by_dim)
    run = UserRun(user=user, beliefs={d: Belief() for d in {d for m in matrix.values() for d in m}})
    now = START
    last_game: str | None = None

    for s in range(1, sessions + 1):
        if s > 1:
            gap = int(rng.integers(user.gap_days[0], user.gap_days[1] + 1))
            now += timedelta(days=gap)
            user.forget(gap)
            run.beliefs = {d: drift(b, now) for d, b in run.beliefs.items()}

        if s == 1:
            # Onboarding battery at Assess difficulty (UW1).
            for gid in registry.batteries["onboarding"].games:
                game = registry.game(gid)
                primary = game.primary_dims[0]
                level = next_level(run.beliefs[primary], TARGET_P["assess"])
                play_round(run, game, "assess", TARGET_P["assess"], level, ONBOARDING_TRIALS,
                           s, now, 0.0, matrix[gid], rng, registry.priors,
                           registry.practice)  # fmt: skip
                now += timedelta(minutes=1)
        else:
            for r in range(ROUNDS_PER_SESSION):
                dim = max(tracked, key=lambda d: run.beliefs[d].sigma)
                options = [g for g in by_dim[dim] if g.id != last_game] or by_dim[dim]
                game = choose_game(options, run, rng)
                mode = choose_mode(run.beliefs[dim], success_mode)  # type: ignore[arg-type]
                target = TARGET_P[mode]
                level = next_level(run.beliefs[dim], target)
                fatigue = user.fatigue_per_round * r
                play_round(run, game, mode, target, level, TRIALS_PER_ROUND, s, now, fatigue,
                           matrix[game.id], rng, registry.priors, registry.practice)  # fmt: skip
                last_game = game.id
                now += timedelta(minutes=4)
        run.snapshots.append(
            Snapshot(s, dict(run.beliefs), {d: user.theta(d) for d in user.theta0})
        )
    return run
