"""`make eval`: the 11 evaluation experiments of docs/plan/15, one figure each in docs/figures/ and
one summary table, docs/figures/eval_summary.md (WP4.2).

Each experiment calls the code that already checks it elsewhere:

- 1-5: the offline simulator (`make sim`, simulator/experiments.py), 200 people.
- 6: the same simulator with long gaps, or 50-150 ms of extra device lag after the warm-up.
- 7: ACS weight sensitivity (backend/acs/sensitivity.py).
- 8: the coach's draft-verify-repair loop (backend/agent/nodes/talk.py) on facts packets built by
  the real `reflect` node, with the local model when Ollama has it, else the stub coach.
- 9: the growth forecast's held-out coverage, read from its model card (retraining needs the
  2.6 GB Lumosity file and about 7 GB of memory: `make ml-data ml-train`).
- 10: the bandit against random game choice (simulator/bandit.py), as in its test.
- 11: simulated people through the real graph with every model failing, Qdrant unreachable, and
  both, in a throwaway database (EVAL_DATABASE_URL); skipped if Postgres is down.

`--graph` also runs experiments 1-5 through the real graph (`make sim-graph`, about 15 minutes)
in the same throwaway database. `--quick` uses tiny sizes (the smoke test).
"""

import argparse
import asyncio
import copy
import logging
import os
import re
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import NormalDist
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np

from backend.registry.loader import load_registry
from backend.registry.models import Game, Registry
from simulator.__main__ import SESSIONS, plots, simulate
from simulator.experiments import (
    coverage,
    established_tracked,
    flagged,
    gate,
    onboarding_sigma,
    recovery,
)
from simulator.population import make_population
from simulator.run import UserRun, random_game, simulate_user

SEED = 2026
DEFAULT_DB = "postgresql://lodestar:lodestar@localhost:5442/lodestar_eval"
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"


@dataclass(frozen=True)
class Sizes:
    users: int = 200  # experiments 1-6 (as in CI)
    acs_users: int = 200
    # One per persona. A local-model call takes 15-60 s on a laptop CPU and most drafts need a
    # repair, so each reply costs 1-3 calls; raise it with --coach-drafts (make eval COACH_N=).
    coach_drafts: int = 4
    bandit: tuple[int, int, int] = (600, 200, 30)  # prior people, compared people, sessions
    graph_users: int = 6  # experiment 11, per condition
    graph_sessions: int = 3


QUICK = Sizes(
    users=24, acs_users=30, coach_drafts=2, bandit=(40, 12, 8), graph_users=1, graph_sessions=2
)


@dataclass(frozen=True)
class Row:
    num: str
    question: str
    result: str
    target: str
    status: str  # pass, FAIL, reported, skipped
    figure: str = ""


def _plt() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 9})
    return plt


def _save(fig: Any, out: Path, name: str) -> str:
    fig.tight_layout()
    fig.savefig(out / name, dpi=120)
    _plt().close(fig)
    return name


def _bars(ax: Any, labels: list[str], values: list[float], fmt: str = "{:.2f}") -> None:
    bars = ax.bar(labels, values, color=BLUE, width=0.6)
    ax.bar_label(bars, [fmt.format(v) for v in values], padding=2)


# 1-5 -------------------------------------------------------------------------------------------


def exp_1_to_5(registry: Registry, n: int, out: Path) -> list[Row]:
    runs, bad_runs = simulate(registry, n, SEED)
    g = gate(runs, bad_runs, registry)
    plots(runs, g.dims, g.recovery, g.success, out)  # sim_recovery.png, sim_success.png
    plt = _plt()

    nominal = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    observed = [coverage(runs, g.dims, [3, 10], NormalDist().inv_cdf(0.5 + p / 2)) for p in nominal]
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.plot([0.45, 1], [0.45, 1], color=GREY, linewidth=1, label="Perfectly honest")
    ax.plot(nominal, observed, color=BLUE, marker="o", linewidth=2, label="Observed")
    ax.plot([0.8, 0.8], [0.75, 0.85], color=GREY, linewidth=8, alpha=0.4, label="Target at 80%")
    ax.set_xlabel("Stated range (share that should contain the true skill)")
    ax.set_ylabel("Share that does (sessions 3 and 10)")
    ax.set_title("2. Are the ranges honest?")
    ax.legend(loc="upper left", frameon=False)
    fig2 = _save(fig, out, "eval_02_ranges.png")

    sigma = onboarding_sigma(runs, registry.core_skills())
    names = sorted(sigma)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    _bars(
        ax,
        [registry.dimension(d).name.replace(" ", "\n") for d in names],
        [sigma[d] for d in names],
    )
    ax.axhline(0.8, color=GREY, linestyle="--", linewidth=1, label="Target: below 0.8")
    ax.set_ylabel("Mean sigma after the warm-up")
    ax.set_title("4. Is the warm-up enough? (core skills)")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper right", frameon=False)
    fig4 = _save(fig, out, "eval_04_warmup.png")

    kinds = ["normal", "random_clicker", "cheater"]
    shares = [
        float(np.mean([flagged(r) for r in bad_runs if r.user.kind == k] or [0.0])) for k in kinds
    ]
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    _bars(ax, ["Normal", "Random clicker", "Too fast and\nalways right"], shares, "{:.0%}")
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Share flagged as bad data")
    ax.set_title("5. Do we catch bad data?")
    fig5 = _save(fig, out, "eval_05_bad_data.png")

    figures = ["sim_recovery.png", fig2, "sim_success.png", fig4, fig5]
    rows = []
    for i, (name, value, target, ok) in enumerate(g.checks):
        num, question = name.split(". ", 1)
        rows.append(Row(num, question, value, target, "pass" if ok else "FAIL", figures[i]))
    rec = g.recovery
    rows[0] = replace(
        rows[0],
        result=f"{rec[3].mean_r:.3f} (after 1 session: "
        f"{rec[1].mean_r:.3f}, after 10: {rec[10].mean_r:.3f})",
    )
    return rows


# 6 ---------------------------------------------------------------------------------------------


def _lag_after_warmup(seed: int):  # type: ignore[no-untyped-def]
    """Game choice only happens after the warm-up battery, so the extra lag starts there."""

    def choose(options: list[Game], run: UserRun, rng: np.random.Generator) -> Game:
        if run.user.device_lag_ms == 0:
            run.user.device_lag_ms = float(
                np.random.default_rng([seed, run.user.user_id, 6]).uniform(50, 150)
            )
        return random_game(options, run, rng)

    return choose


def exp6_gaps_and_lag(registry: Registry, n: int, out: Path) -> Row:
    people = make_population(registry, n, np.random.default_rng([SEED, 6]))
    long_gaps = copy.deepcopy(people)
    for p in long_gaps:
        p.gap_days = (7, 21)
    conditions = {
        "As usual (1-3 days apart)": (people, random_game),
        "Missed sessions (7-21 days apart)": (long_gaps, random_game),
        "50-150 ms extra lag after warm-up": (people, _lag_after_warmup(SEED)),
    }
    rmse: dict[str, list[float]] = {}
    for label, (group, choose) in conditions.items():
        runs = [
            simulate_user(
                copy.deepcopy(p),
                registry,
                SESSIONS,
                np.random.default_rng([SEED, p.user_id]),
                choose_game=choose,
            )
            for p in group
        ]
        dims = established_tracked(registry, runs)
        rmse[label] = [
            float(np.mean(list(recovery(runs, dims, s).rmse_by_dim.values())))
            for s in range(1, SESSIONS + 1)
        ]
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6, 3.8))
    for (label, ys), color in zip(rmse.items(), (BLUE, ORANGE, AQUA), strict=True):
        ax.plot(
            range(1, SESSIONS + 1),
            ys,
            color=color,
            linewidth=2,
            marker="o",
            markersize=4,
            label=label,
        )
    ax.set_xlabel("Session")
    ax.set_ylabel("Error of the estimate (RMSE)")
    ax.set_title("6. Robust to gaps and lag?")
    ax.legend(frameon=False)
    figure = _save(fig, out, "eval_06_gaps_lag.png")
    base, gaps, lag = (v[-1] for v in rmse.values())
    return Row(
        "6",
        "Robust to gaps and lag? (RMSE after 10 sessions)",
        f"{base:.3f} usual, {gaps:.3f} with gaps ({gaps - base:+.3f}), "
        f"{lag:.3f} with lag ({lag - base:+.3f})",
        "Small degradation, reported",
        "reported",
        figure,
    )


# 7 ---------------------------------------------------------------------------------------------


def exp7_acs(n: int, out: Path) -> Row:
    from backend.acs.sensitivity import analyse

    s = analyse(n)
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5, 4))
    names = {
        "V": "Verification",
        "A": "Autonomy",
        "I": "Iteration",
        "C": "Clarification",
        "R": "Responsible use",
    }
    labels = [f"{names[k[0]]} {float(k[1:]) * 100:+.0f}" for k in s.shifts]
    ax.barh(labels, list(s.shifts.values()), color=BLUE, height=0.6)
    ax.axvline(0.9, color=GREY, linestyle="--", linewidth=1)
    ax.set_xlim(0.8, 1.0)
    ax.invert_yaxis()
    ax.set_xlabel("Rank agreement with the chosen weights (Spearman; target above 0.9)")
    ax.set_title("7. Is the ACS stable? (one weight moved by 5 points)")
    figure = _save(fig, out, "eval_07_acs.png")
    return Row(
        "7",
        "Is the ACS stable? (worst of 10 single-weight shifts)",
        f"{s.worst_rho:.3f} ({n} simulated people)",
        "Spearman > 0.9",
        "pass" if s.worst_rho > 0.9 else "FAIL",
        figure,
    )


# 8 ---------------------------------------------------------------------------------------------


def _local_model_ready(settings: Any) -> bool:
    import httpx

    try:
        tags = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3).json()
    except httpx.HTTPError, ValueError:
        return False
    return any(m.get("name") == settings.local_model for m in tags.get("models", []))


async def _packets(registry: Registry, n: int, ctx: Any) -> list[Any]:
    """Facts packets from the real `reflect` node, for simulated rounds."""
    from backend.agent.nodes.talk import reflect
    from backend.agent.state import LodestarState
    from backend.contracts.events import DimensionChange
    from backend.contracts.session import RoundSummary
    from backend.contracts.twin import ForecastBand

    rng = np.random.default_rng([SEED, 8])
    games = [g for g in registry.games if g.phase == "P1" and g.kind == "game"]
    packets = []
    for i in range(n):
        game = games[int(rng.integers(len(games)))]
        dim = game.primary_dims[0]
        mu = float(rng.normal(0, 0.8))
        after = mu + float(rng.normal(0.08, 0.15))
        answered = 12
        correct = int(rng.binomial(answered, 0.75))
        change = DimensionChange(
            dim=dim, mu_before=mu, mu_after=after, sigma_before=0.7, sigma_after=0.62, n_after=3 + i
        )
        summary = RoundSummary(
            round_id=str(uuid4()),
            game_id=game.id,
            status="completed",
            mean_score=correct / answered,
            accuracy=correct / answered,
            correct=correct,
            answered=answered,
            observations=answered,
            changes=[change],
        )
        forecast = (
            {
                dim: ForecastBand(
                    dim=dim,
                    sessions_ahead=5,
                    low=after - 0.3,
                    median=after + 0.2,
                    high=after + 0.7,
                    source="model",
                )
            }
            if i % 2
            else {}
        )
        state = LodestarState(
            user_id=str(ctx.user_id),
            session_id=str(ctx.session_id),
            trigger="ui",
            persona="willow",
            last_round=summary,
            forecast=forecast,
        )
        packets.append((await reflect.__wrapped__(state, SimpleNamespace(context=ctx)))["facts"])  # type: ignore[attr-defined]
    return packets


async def exp8_coach(registry: Registry, n: int, out: Path, stub_only: bool) -> Row:
    from backend.agent.context import LodestarContext, Services
    from backend.agent.nodes.talk import draft_verified
    from backend.coach.verify import verify
    from backend.config import get_settings
    from backend.contracts.llm import LlmSelection
    from backend.llm.factory import LlmFactory

    settings = get_settings()
    local = not stub_only and _local_model_ready(settings)
    selection = (
        LlmSelection(mode="local", provider="ollama", model=settings.local_model)
        if local
        else LlmSelection(mode="stub", provider="stub", model="stub")
    )
    llm = LlmFactory(registry, settings, engine=None, call_timeout_s=120)  # type: ignore[arg-type]
    ctx = LodestarContext(
        user_id=uuid4(),
        session_id=uuid4(),
        llm=selection,
        consent=frozenset(),
        services=Services(engine=None, registry=registry, llm=llm),
    )  # type: ignore[arg-type]
    personas = ["willow", "spark", "sage", "buddy"]
    names = [d.name for d in registry.dimensions]
    first = repaired = template = final_ok = 0
    for i, packet in enumerate(await _packets(registry, n, ctx)):
        persona = personas[i % len(personas)]
        text, reply, _ = await draft_verified(
            ctx,
            packet,
            persona,
            "Write the short message shown after this game.",  # type: ignore[arg-type]
        )
        first += reply.first_draft_passed
        repaired += not reply.first_draft_passed and not reply.used_template
        template += reply.used_template
        final_ok += verify(text, packet, names, persona).ok  # type: ignore[arg-type]
    model = f"local model {settings.local_model}" if local else "stub coach (no local model)"
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5, 3.5))
    _bars(
        ax,
        [
            "First draft\npassed",
            "Passed after\nrepair",
            "Fell back to\ntemplate",
            "Final reply\npassed",
        ],
        [first / n, repaired / n, template / n, final_ok / n],
        "{:.0%}",
    )
    ax.set_ylim(0, 1.15)
    ax.set_ylabel(f"Share of {n} replies")
    ax.set_title(f"8. Is the coach faithful? ({model})")
    figure = _save(fig, out, "eval_08_coach.png")
    return Row(
        "8",
        f"Is the coach faithful? ({model}, {n} replies, 4 personas)",
        f"first draft {first}/{n}, after repair {first + repaired}/{n}, template "
        f"{template}/{n}, final {final_ok}/{n}",
        "Final 100%, first draft reported",
        "pass" if final_ok == n else "FAIL",
        figure,
    )


# 9 ---------------------------------------------------------------------------------------------

CARD = Path("backend/ml/model_cards/growth_forecast.md")
_HORIZON = re.compile(r"^\| k=(\d+) \| ([\d.]+)% \| ([\d.]+) \|", re.MULTILINE)
_OVERALL = re.compile(r"Observed coverage of the 80% range: \*\*([\d.]+)%\*\*")


def exp9_forecast(out: Path) -> Row:
    text = CARD.read_text(encoding="utf-8") if CARD.exists() else ""
    rows = [(int(k), float(c) / 100, float(w)) for k, c, w in _HORIZON.findall(text)]
    overall = _OVERALL.search(text)
    if not rows or overall is None:
        return Row(
            "9",
            "Does the forecast's range hold?",
            "no model card yet",
            "80% nominal, report observed",
            "skipped",
        )
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ks = [str(k) for k, _, _ in rows]
    _bars(ax, ks, [c for _, c, _ in rows], "{:.1%}")
    ax.axhline(0.8, color=GREY, linestyle="--", linewidth=1, label="Stated: 80%")
    ax.set_ylim(0, 1)
    ax.set_xlabel("Sessions ahead (k)")
    ax.set_ylabel("Held-out people inside the range")
    ax.set_title("9. Does the forecast's range hold? (Lumosity)")
    ax.legend(loc="lower right", frameon=False)
    figure = _save(fig, out, "eval_09_forecast.png")
    return Row(
        "9",
        "Does the forecast's range hold? (held-out Lumosity players, from the model card)",
        f"{overall.group(1)}% observed (k=1 to 20: "
        f"{min(c for _, c, _ in rows):.1%}-{max(c for _, c, _ in rows):.1%})",
        "80% nominal, report observed",
        "reported",
        figure,
    )


# 10 --------------------------------------------------------------------------------------------


def exp10_bandit(registry: Registry, sizes: tuple[int, int, int], out: Path) -> Row:
    from simulator.bandit import compare

    first, users, sessions = sizes
    c = compare(registry, first, users, sessions, SEED)
    plt = _plt()
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    _bars(ax, ["Random game", "Bandit"], [c.random_gain, c.bandit_gain], "{:.2f}")
    ax.set_ylabel(f"True skill gained per person ({sessions} sessions)")
    ax.set_title(
        f"10. Does the bandit help? (+{c.diff_low:.3f} to +{c.diff_high:.3f}, 95%)"
        if c.diff_low > 0
        else f"10. Does the bandit help? ({c.diff_low:+.3f} to {c.diff_high:+.3f}, 95%)"
    )
    figure = _save(fig, out, "eval_10_bandit.png")
    return Row(
        "10",
        f"Does the bandit help? ({users} paired people, prior from {first})",
        f"{c.random_gain:.3f} random vs {c.bandit_gain:.3f} bandit; difference "
        f"{c.diff_low:+.3f} to {c.diff_high:+.3f} (95%), {c.share_better:.0%} gained more",
        "Report the difference",
        "reported",
        figure,
    )


# 11 --------------------------------------------------------------------------------------------


def fresh_database(url: str) -> bool:
    """Drop and recreate the eval database and migrate it; False if Postgres is down."""
    import psycopg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from backend.db.engine import libpq_url, sync_url

    name = make_url(url).database
    admin = libpq_url(make_url(url).set(database="postgres").render_as_string(hide_password=False))
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError:
        return False
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    command.upgrade(config, "head")
    return True


def drop_database(url: str) -> None:
    import psycopg
    from sqlalchemy.engine import make_url

    from backend.db.engine import libpq_url

    admin = libpq_url(make_url(url).set(database="postgres").render_as_string(hide_password=False))
    with psycopg.connect(admin, autocommit=True, connect_timeout=3) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{make_url(url).database}" WITH (FORCE)')


def _model_down(_: Any) -> str:
    raise ConnectionError("simulated outage: every model is unreachable")


async def exp11_degradation(
    registry: Registry, users: int, sessions: int, db_url: str, out: Path
) -> Row:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
    from qdrant_client import AsyncQdrantClient
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.agent.context import Services
    from backend.agent.graph import checkpointer, compile_graph
    from backend.agent.runner import SessionRunner
    from backend.config import get_settings
    from backend.db import tables as t
    from backend.db.engine import libpq_url, sync_url
    from backend.llm.factory import LlmFactory
    from backend.memory.embeddings import Embedder
    from backend.memory.langgraph_store import QdrantStore
    from backend.memory.store import MemoryStore
    from simulator.graph_run import simulate_through_graph

    question = "Does the agent degrade gracefully? (sessions completed through the real graph)"
    if not fresh_database(db_url):
        return Row(
            "11", question, "skipped: Postgres not reachable (make up)", "100% completed", "skipped"
        )
    settings = get_settings()
    engine = create_async_engine(sync_url(db_url))
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        libpq_url(db_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    embedder = Embedder()
    # The outages are deliberate: keep their expected warnings out of the output.
    logging.disable(logging.WARNING)
    warnings.filterwarnings("ignore", message="Failed to obtain server version")

    def dead_qdrant() -> MemoryStore:  # nothing listens on port 9
        return MemoryStore(AsyncQdrantClient(url="http://127.0.0.1:9", timeout=2), embedder)

    conditions = {
        "Every model down": (_model_down, None),
        "Qdrant down": (None, dead_qdrant),
        "Both down": (_model_down, dead_qdrant),
    }
    completed: dict[str, tuple[int, int]] = {}
    try:
        for label, (responder, memory_factory) in conditions.items():
            memory = memory_factory() if memory_factory else None
            services = Services(
                engine=engine,
                registry=registry,
                memory=memory,
                llm=LlmFactory(registry, settings, engine, stub_responder=responder),
            )
            store = QdrantStore(memory) if memory else None
            runner = SessionRunner(
                compile_graph(checkpointer(pool), store), services, settings.local_model
            )
            rng = np.random.default_rng([SEED, 11])
            done = 0
            for person in make_population(registry, users, rng, kinds={"normal": 1.0}):
                try:
                    runs = await simulate_through_graph(
                        runner, engine, registry, [person], sessions, rng
                    )
                except Exception as exc:  # a crash is what this experiment counts
                    print(f"  {label}: session crashed ({type(exc).__name__})")
                    continue
                async with engine.connect() as conn:
                    done += (
                        await conn.execute(
                            select(func.count()).where(
                                t.sessions.c.user_id == runs[0].user_id,
                                t.sessions.c.status == "ended",
                            )
                        )
                    ).scalar_one()
            completed[label] = (done, users * sessions)
    finally:
        logging.disable(logging.NOTSET)
        await pool.close()
        await engine.dispose()
        drop_database(db_url)

    plt = _plt()
    fig, ax = plt.subplots(figsize=(5, 3.5))
    _bars(ax, list(completed), [d / n for d, n in completed.values()], "{:.0%}")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Sessions completed")
    ax.set_title("11. Does the agent degrade gracefully?")
    figure = _save(fig, out, "eval_11_degradation.png")
    ok = all(d == n for d, n in completed.values())
    return Row(
        "11",
        f"{question}, {users * sessions} sessions per condition",
        ", ".join(f"{k}: {d}/{n}" for k, (d, n) in completed.items()),
        "100% completed",
        "pass" if ok else "FAIL",
        figure,
    )


# Summary ---------------------------------------------------------------------------------------


def summary(rows: list[Row], sizes: Sizes, minutes: float, graph: str | None) -> str:
    lines = [
        "# Evaluation results (`make eval`)",
        "",
        f"The 11 experiments of docs/plan/15, seed {SEED}, in {minutes:.1f} minutes. Simulated "
        f"people: {sizes.users} for 1-6 (CI also uses 200), {sizes.acs_users} for 7, "
        f"{sizes.bandit[1]} paired for 10; experiment 11 plays {sizes.graph_users} x "
        f"{sizes.graph_sessions} sessions per condition through the real graph. "
        "Status: pass or FAIL against the target; reported where the target is to report a "
        "number; skipped when a dependency is missing.",
        "",
        "| # | Question | Result | Target | Status | Figure |",
        "|---|---|---|---|---|---|",
        *(
            f"| {r.num} | {r.question} | {r.result} | {r.target} | {r.status} | "
            + (f"[{r.figure}]({r.figure})" if r.figure else "-")
            + " |"
            for r in rows
        ),
        "",
        graph
        or "Experiments 1-5 through the real graph are not part of the default run: "
        "`make eval GRAPH=120` adds them (about 15 minutes), see "
        "[sim_graph_summary.md](sim_graph_summary.md).",
        "",
    ]
    return "\n".join(lines)


def run_graph_gate(db_url: str, users: int) -> str:
    if not fresh_database(db_url):
        return "Through the real graph: skipped, Postgres not reachable."
    try:
        code = subprocess.call(
            [sys.executable, "-m", "simulator.graph_gate", "--users", str(users)],
            env={**os.environ, "DATABASE_URL": db_url},
        )
    finally:
        drop_database(db_url)
    status = "all targets met" if code == 0 else "a target was missed"
    return (
        f"Experiments 1-5 through the real graph ({users} people): {status}, see "
        "[sim_graph_summary.md](sim_graph_summary.md)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/figures"))
    parser.add_argument("--quick", action="store_true", help="tiny sizes (smoke test)")
    parser.add_argument("--stub-coach", action="store_true", help="experiment 8 without Ollama")
    parser.add_argument("--coach-drafts", type=int, help="replies drafted in experiment 8")
    parser.add_argument(
        "--graph",
        type=int,
        default=0,
        metavar="N",
        help="also run experiments 1-5 through the real graph with N people",
    )
    args = parser.parse_args(argv)
    sizes = QUICK if args.quick else Sizes()
    if args.coach_drafts:
        sizes = replace(sizes, coach_drafts=args.coach_drafts)
    db_url = os.environ.get("EVAL_DATABASE_URL", DEFAULT_DB)
    args.out.mkdir(parents=True, exist_ok=True)
    registry = load_registry()
    started = time.time()

    steps: list[tuple[str, Any]] = [
        ("1-5", lambda: exp_1_to_5(registry, sizes.users, args.out)),
        ("6", lambda: exp6_gaps_and_lag(registry, sizes.users, args.out)),
        ("7", lambda: exp7_acs(sizes.acs_users, args.out)),
        (
            "8",
            lambda: asyncio.run(
                exp8_coach(registry, sizes.coach_drafts, args.out, args.stub_coach)
            ),
        ),
        ("9", lambda: exp9_forecast(args.out)),
        ("10", lambda: exp10_bandit(registry, sizes.bandit, args.out)),
        (
            "11",
            lambda: asyncio.run(
                exp11_degradation(
                    registry, sizes.graph_users, sizes.graph_sessions, db_url, args.out
                )
            ),
        ),
    ]
    rows: list[Row] = []
    for label, step in steps:
        t0 = time.time()
        result = step()
        rows.extend(result if isinstance(result, list) else [result])
        print(f"experiment {label}: {time.time() - t0:.0f} s", flush=True)
    graph = run_graph_gate(db_url, args.graph) if args.graph else None
    report = summary(rows, sizes, (time.time() - started) / 60, graph)
    (args.out / "eval_summary.md").write_text(report, encoding="utf-8")
    print(report)
    return 1 if any(r.status == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
