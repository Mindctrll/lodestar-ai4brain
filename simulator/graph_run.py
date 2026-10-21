"""Simulated users played through the real agent graph (docs/plan/15; WP2.3 "Done when").

Unlike `simulator.run`, which calls the scoring engine directly, this drives the whole loop:
sessions are created, the graph plans and pauses, simulated answers go through the same trial
ingestion as the browser, and the graph is resumed with the round result and the behaviour
signals the browser would send (WP2.9). Days pass between sessions by moving the user's
timestamps back, so drift and check-ups behave as they would for a real person.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.runner import SessionRunner
from backend.contracts.affect import BehaviourSignals
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.twin_store import create_user, record_trials
from backend.registry.models import Registry
from backend.scoring.kalman_elo import Belief, drift
from simulator.population import SimUser
from simulator.responses import answer
from simulator.run import RoundLog, Snapshot, UserRun

TRIALS = 12


@dataclass
class PlayedRound:
    round_id: UUID
    game_id: str
    mode: str
    target_p: float
    score: float | None = None
    verdict: str | None = None  # monitor's call after the round
    session: int = 0
    trust: float | None = None


@dataclass
class GraphRun:
    user: SimUser
    user_id: UUID
    rounds: list[PlayedRound] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)

    def as_user_run(self) -> UserRun:
        """The same shape the offline simulator produces, so experiments 1-5 apply as they are."""
        logs = [
            RoundLog(
                session=r.session,
                game_id=r.game_id,
                mode="balanced" if r.mode == "train" and r.target_p == 0.8 else r.mode,
                target_p=r.target_p,
                mean_score=r.score,
                accuracy=r.score or 0.0,
            )
            for r in self.rounds
        ]
        last = self.snapshots[-1].beliefs if self.snapshots else {}
        zero = sum(1 for r in self.rounds if r.trust == 0)
        return UserRun(self.user, dict(last), logs, list(self.snapshots), zero)


def behaviour(user: SimUser, correct: list[bool]) -> BehaviourSignals:
    """What the browser would see: miss streaks, and rushed taps from a frustration-prone user
    after a miss."""
    run = longest = rushed = 0
    for i, c in enumerate(correct):
        run = 0 if c else run + 1
        longest = max(longest, run)
        if user.kind == "frustration_prone" and not c and i > 0 and not correct[i - 1]:
            rushed += 1
    return BehaviourSignals(error_streak=longest, rapid_taps=rushed)


def _interrupt(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for e in events:
        if e["kind"] == "interrupt":
            spec: dict[str, Any] = e["payload"]["spec"]
            return spec
    return None


async def _play(
    runner: SessionRunner,
    engine: AsyncEngine,
    registry: Registry,
    run: GraphRun,
    session_id: UUID,
    spec: dict[str, Any],
    rng: np.random.Generator,
    session: int = 0,
) -> list[dict[str, Any]]:
    game = registry.game(spec["game_id"])
    primary = game.primary_dims[0]
    deadline = spec["knobs"].get("deadline_ms") if game.scoring == "hshs" else None
    start = datetime.now(UTC)
    trials = []
    miss_run = 0
    for i in range(TRIALS):
        a = answer(run.user, game, primary, spec["difficulty_b"], deadline, 0.0, rng, miss_run)
        miss_run = 0 if a.correct else miss_run + 1
        trials.append(
            TrialEvent(
                trial_id=uuid4(),
                round_id=UUID(spec["round_id"]),
                session_id=session_id,
                game_id=game.id,
                level=spec["level"],
                trial_index=i,
                stimulus={"deadline_ms": deadline} if deadline else {},
                correct=a.correct,
                rt_ms=a.rt_ms,
                ts=start + timedelta(seconds=4 * i),
            )
        )
    async with engine.begin() as conn:
        await record_trials(conn, run.user_id, trials)
    for dim, loading in game.dims.items():
        if dim in run.user.gain:
            run.user.practise(dim, loading)
    played = PlayedRound(
        UUID(spec["round_id"]), game.id, spec["mode"], spec["target_p"], session=session
    )
    run.rounds.append(played)
    signals = behaviour(run.user, [bool(tr.correct) for tr in trials])
    result = {
        "round_id": spec["round_id"],
        "game_id": game.id,
        "status": "completed",
        "trial_count": TRIALS,
        "final_level": spec["level"],
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=1)).isoformat(),
        "behaviour": signals.model_dump(mode="json"),
    }
    events = [e async for e in runner.run(run.user_id, session_id, resume=result)]
    played.verdict = next(
        (e["chosen"] for e in events if e["kind"] == "decision" and e["node"] == "monitor"), None
    )
    return events


async def _days_pass(engine: AsyncEngine, run: GraphRun, days: int) -> None:
    """Days between sessions without touching the clock: the user's timestamps move back by the
    gap, so the app's own staleness drift and 14-day check-up see the time pass (docs/plan/07),
    and the simulated person forgets a little, as in the offline simulator."""
    run.user.forget(days)
    shift = timedelta(days=days)
    async with engine.begin() as conn:
        await conn.execute(
            t.dimension_state.update()
            .where(t.dimension_state.c.user_id == run.user_id)
            .values(last_practised=t.dimension_state.c.last_practised - shift)
        )
        await conn.execute(
            t.sessions.update()
            .where(t.sessions.c.user_id == run.user_id)
            .values(
                started_at=t.sessions.c.started_at - shift,
                ended_at=t.sessions.c.ended_at - shift,
            )
        )


async def _snapshot(
    engine: AsyncEngine, registry: Registry, run: GraphRun, session: int
) -> Snapshot:
    """The Twin as the app shows it after a session (with staleness drift applied at read time,
    as read_twin does), next to the simulated truth."""
    now = datetime.now(UTC)
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(t.dimension_state).where(t.dimension_state.c.user_id == run.user_id)
        )
        stored = {r.dim: drift(Belief(r.mu, r.sigma, r.n, r.last_practised), now) for r in rows}
    dims = list(run.user.theta0)
    return Snapshot(
        session,
        {d: stored.get(d, Belief()) for d in dims},
        {d: run.user.theta(d) for d in dims},
    )


async def simulate_through_graph(
    runner: SessionRunner,
    engine: AsyncEngine,
    registry: Registry,
    users: list[SimUser],
    sessions: int,
    rng: np.random.Generator,
) -> list[GraphRun]:
    runs: list[GraphRun] = []
    for user in users:
        async with engine.begin() as conn:
            user_id, _ = await create_user(conn)
            await conn.execute(
                t.llm_selection.insert().values(
                    user_id=user_id, mode="stub", provider="stub", model="stub"
                )
            )
        run = GraphRun(user, user_id)
        for s in range(1, sessions + 1):
            session_id = await runner.create_session(user_id, "ui")
            spec = _interrupt([e async for e in runner.run(user_id, session_id)])
            while spec is not None:
                events = await _play(runner, engine, registry, run, session_id, spec, rng, s)
                spec = _interrupt(events)
            run.snapshots.append(await _snapshot(engine, registry, run, s))
            if s < sessions:
                await _days_pass(engine, run, int(rng.integers(*user.gap_days, endpoint=True)))
        async with engine.connect() as conn:
            scores = dict(
                (
                    await conn.execute(
                        select(t.rounds.c.round_id, t.rounds.c.score).where(
                            t.rounds.c.user_id == user_id
                        )
                    )
                ).all()
            )
            trust = {
                str(p["round_id"]): float(p["inputs"]["trust"])
                for (p,) in await conn.execute(
                    select(t.events.c.payload).where(
                        t.events.c.user_id == user_id, t.events.c.type == "twin.updated"
                    )
                )
            }
        for r in run.rounds:
            r.score = scores.get(r.round_id)
            r.trust = trust.get(str(r.round_id))
        runs.append(run)
    return runs


def ease_rate(runs: list[GraphRun], kind: str) -> float:
    """Share of rounds after which Najma eased off or suggested a break, for one user type."""
    verdicts = [r.verdict for run in runs if run.user.kind == kind for r in run.rounds]
    return sum(v in ("ease", "break") for v in verdicts) / len(verdicts) if verdicts else 0.0


def balanced_success(runs: list[GraphRun]) -> tuple[float, int]:
    scores = [
        r.score
        for run in runs
        for r in run.rounds
        if r.mode == "train" and r.target_p == 0.8 and r.score is not None
    ]
    return (float(np.mean(scores)) if scores else float("nan")), len(scores)


async def main_async(users: int, sessions: int, seed: int) -> int:  # pragma: no cover - CLI
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from backend.agent.context import Services
    from backend.agent.graph import checkpointer, compile_graph
    from backend.config import get_settings
    from backend.db.engine import get_async_engine, libpq_url
    from backend.llm.factory import LlmFactory
    from backend.registry.loader import load_registry
    from simulator.population import make_population

    registry = load_registry()
    settings = get_settings()
    engine = get_async_engine()
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        libpq_url(),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    services = Services(
        engine=engine, registry=registry, llm=LlmFactory(registry, settings, engine)
    )
    runner = SessionRunner(compile_graph(checkpointer(pool)), services, settings.local_model)
    rng = np.random.default_rng(seed)
    population = make_population(registry, users, rng)
    runs = await simulate_through_graph(runner, engine, registry, population, sessions, rng)
    success, n = balanced_success(runs)
    print(
        f"Balanced success through the graph: {success:.3f} over {n} rounds (target 0.80 +/- 0.05)"
    )
    await pool.close()
    await engine.dispose()
    return 0 if abs(success - 0.8) <= 0.05 else 1


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.users, args.sessions, args.seed)))
