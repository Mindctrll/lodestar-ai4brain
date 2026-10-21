"""Wave 2 gate (docs/plan/16): the simulator played through the real agent graph, checked against
every threshold of docs/plan/15 experiments 1-5 with the same definitions as `make sim`.

Run with `make sim-graph` (about half an hour on a laptop CPU for 120 users and 10 sessions:
every round goes through planning, the pause, scoring in Postgres, monitor and coaching).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from simulator.experiments import gate
from simulator.graph_run import simulate_through_graph
from simulator.population import make_population

SESSIONS = 10


async def main_async(users: int, sessions: int, seed: int) -> tuple[str, bool]:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from backend.agent.context import Services
    from backend.agent.graph import checkpointer, compile_graph
    from backend.agent.runner import SessionRunner
    from backend.config import get_settings
    from backend.db.engine import get_async_engine, libpq_url
    from backend.llm.factory import LlmFactory
    from backend.registry.loader import load_registry

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
    started = time.time()
    population = make_population(registry, users, rng)
    runs = await simulate_through_graph(runner, engine, registry, population, sessions, rng)
    bad = make_population(
        registry, max(20, users // 5), rng,
        kinds={"normal": 0.6, "random_clicker": 0.2, "cheater": 0.2},
    )  # fmt: skip
    bad_runs = await simulate_through_graph(runner, engine, registry, bad, 3, rng)
    result = gate([r.as_user_run() for r in runs], [r.as_user_run() for r in bad_runs], registry)
    rounds = sum(len(r.rounds) for r in runs + bad_runs)
    minutes = (time.time() - started) / 60
    lines = [
        f"# Simulator through the real graph ({users} users, {sessions} sessions, seed {seed})",
        "",
        f"{rounds} rounds played through LangGraph, Postgres and the stub coach in "
        f"{minutes:.0f} minutes. Same experiments and targets as `make sim` (docs/plan/15).",
        "",
        "| Experiment | Result | Target | Pass |",
        "|---|---|---|---|",
        *(
            f"| {name} | {value} | {target} | {'yes' if ok else 'NO'} |"
            for name, value, target, ok in result.checks
        ),
        "",
        "Recovery r by session: "
        + ", ".join(f"after {s}: {rec.mean_r:.3f}" for s, rec in result.recovery.items()),
        "",
    ]
    await pool.close()
    await engine.dispose()
    return "\n".join(lines), result.passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=120)
    parser.add_argument("--sessions", type=int, default=SESSIONS)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    report, passed = asyncio.run(main_async(args.users, args.sessions, args.seed))
    print(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sim_graph_summary.md").write_text(report, encoding="utf-8")
    sys.exit(0 if passed else 1)
