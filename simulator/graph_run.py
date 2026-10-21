"""Simulated users played through the real agent graph (docs/plan/15; WP2.3 "Done when").

Unlike `simulator.run`, which calls the scoring engine directly, this drives the whole loop:
sessions are created, the graph plans and pauses, simulated answers go through the same trial
ingestion as the browser, and the graph is resumed with the round result.
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
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.twin_store import create_user, record_trials
from backend.registry.models import Registry
from simulator.population import SimUser
from simulator.responses import answer

TRIALS = 12


@dataclass
class PlayedRound:
    round_id: UUID
    game_id: str
    mode: str
    target_p: float
    score: float | None = None


@dataclass
class GraphRun:
    user: SimUser
    user_id: UUID
    rounds: list[PlayedRound] = field(default_factory=list)


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
) -> list[dict[str, Any]]:
    game = registry.game(spec["game_id"])
    primary = game.primary_dims[0]
    deadline = spec["knobs"].get("deadline_ms") if game.scoring == "hshs" else None
    start = datetime.now(UTC)
    trials = []
    for i in range(TRIALS):
        a = answer(run.user, game, primary, spec["difficulty_b"], deadline, 0.0, rng)
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
    run.rounds.append(PlayedRound(UUID(spec["round_id"]), game.id, spec["mode"], spec["target_p"]))
    result = {
        "round_id": spec["round_id"],
        "game_id": game.id,
        "status": "completed",
        "trial_count": TRIALS,
        "final_level": spec["level"],
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(minutes=1)).isoformat(),
    }
    return [e async for e in runner.run(run.user_id, session_id, resume=result)]


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
        for _ in range(sessions):
            session_id = await runner.create_session(user_id, "ui")
            spec = _interrupt([e async for e in runner.run(user_id, session_id)])
            while spec is not None:
                spec = _interrupt(await _play(runner, engine, registry, run, session_id, spec, rng))
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
        for r in run.rounds:
            r.score = scores.get(r.round_id)
        runs.append(run)
    return runs


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
