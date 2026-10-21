"""Perception: five nodes that run in parallel at the start of every run (docs/plan/03).

Each has a timeout; a failure leaves its input empty and is recorded in `degraded`, so the
session continues.
"""

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any

from langgraph.runtime import Runtime
from sqlalchemy import func, select

from backend.agent.context import NajmaContext
from backend.agent.state import NajmaState
from backend.agent.telemetry import traced
from backend.contracts.twin import DimensionState, LifeContextWindow, TwinSnapshot
from backend.db import tables as t
from backend.ml.serve import engagement_reading, fatigue_now, forecast_bands, user_history
from backend.scoring.kalman_elo import Belief, drift

PERCEIVE_TIMEOUT_S = 3.0
PERCEIVE_NODES = ("load_twin", "recall_memory", "read_affect", "read_context", "forecast")


async def _guarded(name: str, work: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(work, PERCEIVE_TIMEOUT_S)
    except Exception as exc:
        return {"degraded": [f"{name}:{type(exc).__name__}->empty"]}


async def read_twin_snapshot(ctx: NajmaContext, now: datetime | None = None) -> TwinSnapshot:
    now = now or datetime.now(UTC)
    async with ctx.services.engine.connect() as conn:
        rows = await conn.execute(
            select(t.dimension_state).where(t.dimension_state.c.user_id == ctx.user_id)
        )
        dims = {}
        for r in rows:
            b = drift(Belief(r.mu, r.sigma, r.n, r.last_practised), now)
            dims[r.dim] = DimensionState(
                dim=r.dim, mu=b.mu, sigma=b.sigma, n=b.n, last_practised=b.last_practised
            )
    return TwinSnapshot(user_id=ctx.user_id, as_of=now, dims=dims)


async def read_profile_facts(ctx: NajmaContext, state: NajmaState) -> dict[str, Any]:
    """Goals, the time away since the last session, and the warm-up battery for a new user."""
    async with ctx.services.engine.connect() as conn:
        goals = (
            (
                await conn.execute(
                    select(t.goals.c.dim).where(
                        t.goals.c.user_id == ctx.user_id, t.goals.c.status == "active"
                    )
                )
            )
            .scalars()
            .all()
        )
        scored = (
            await conn.execute(
                select(func.count())
                .select_from(t.rounds)
                .where(t.rounds.c.user_id == ctx.user_id, t.rounds.c.scored_at.is_not(None))
            )
        ).scalar_one()
        last = (
            await conn.execute(
                select(func.max(t.sessions.c.started_at)).where(
                    t.sessions.c.user_id == ctx.user_id,
                    t.sessions.c.session_id != ctx.session_id,
                )
            )
        ).scalar_one_or_none()
    out: dict[str, Any] = {"goal_dims": sorted(set(goals))}
    if last is not None:
        out["away_days"] = (datetime.now(UTC) - last).total_seconds() / 86_400
    if scored == 0 and not state.rounds and not state.onboarding:
        registry = ctx.services.registry
        battery = registry.batteries["onboarding"]
        games = [
            g
            for g in battery.games
            if registry.game(g).available
            and registry.game(g).consent in (None, *ctx.consent)  # e.g. planted mistakes off
        ]
        out["onboarding"] = games
        out["budget"] = state.budget.model_copy(update={"max_rounds": len(games)})
    return out


@traced("load_twin")
async def load_twin(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    async def work() -> dict[str, Any]:
        twin = await read_twin_snapshot(runtime.context)
        return {"twin": twin, **await read_profile_facts(runtime.context, state)}

    return await _guarded("load_twin", work())


@traced("recall_memory")
async def recall_memory(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    memory = runtime.context.services.memory
    if memory is None:
        return {}

    async def work() -> dict[str, Any]:
        # Without a message, look for what usually shapes a session: plans, goals, how they feel.
        query = state.said or "my exams, goals, plans, preferences and how I feel lately"
        return {"memories": await memory.recall(runtime.context.user_id, query)}

    return await _guarded("recall_memory", work())


@traced("read_affect")
async def read_affect(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    # Behaviour-only rules arrive in WP2.9; at session start there is nothing to read yet.
    return {}


@traced("read_context")
async def read_context(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    async def work() -> dict[str, Any]:
        now = datetime.now(UTC)
        async with runtime.context.services.engine.connect() as conn:
            rows = await conn.execute(
                select(t.life_context).where(
                    t.life_context.c.user_id == runtime.context.user_id,
                    t.life_context.c.period.op("@>")(now),
                )
            )
            windows = [
                LifeContextWindow(
                    context_id=r.context_id,
                    label=r.label,
                    start=r.period.lower,
                    end=r.period.upper,
                    weight=r.weight,
                )
                for r in rows
            ]
        return {"context": windows}

    return await _guarded("read_context", work())


@traced("forecast")
async def forecast(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """The models (docs/plan/10): growth bands for each skill with at least three days of
    practice, and, at the start of a session, the engagement risk and the fatigue point."""
    ctx = runtime.context
    services = ctx.services

    async def work() -> dict[str, Any]:
        out: dict[str, Any] = {}
        if services.forecaster is not None:
            history = await user_history(services.engine, ctx.user_id)
            out["forecast"] = forecast_bands(services.forecaster, services.registry, history)
        if state.rounds:
            return out
        if services.engagement is not None:
            async with services.engine.connect() as conn:
                tz = (
                    await conn.execute(
                        select(t.users.c.timezone).where(t.users.c.user_id == ctx.user_id)
                    )
                ).scalar_one_or_none()
            out["engagement"] = await engagement_reading(
                services.engine, services.engagement, ctx.user_id, tz or "UTC", datetime.now(UTC)
            )
        if (point := await fatigue_now(services.engine, ctx.user_id)) is not None:
            out["fatigue_point"] = point
        return out

    return await _guarded("forecast", work())
