"""Dashboard read models (docs/plan/13): stat pills, life-context strips, heatmaps, recent
decisions, a session's trace, and a live "twin updated" stream."""

import asyncio
import contextlib
import datetime as dt
from collections import defaultdict
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import Integer, func, select, text

from backend.api.deps import Conn, CurrentUser, RegistryDep, engine_dep
from backend.contracts.decision import Candidate, Decision
from backend.contracts.views import (
    ContextStrip,
    HourHeatmap,
    ProgressView,
    SkillWeekHeatmap,
    StatPills,
    TraceRow,
)
from backend.db import tables as t
from backend.db.engine import libpq_url
from backend.db.twin_store import NOTIFY_CHANNEL, user_for_token
from backend.scoring.kalman_elo import Belief
from backend.scoring.norms import Norms

router = APIRouter(tags=["twin"])

WEEKS = 8
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOUR_BLOCKS = [(0, 6, "night"), (6, 10, "6-10"), (10, 14, "10-14"), (14, 18, "14-18"),
               (18, 22, "18-22"), (22, 24, "22-24")]  # fmt: skip
MIN_ANSWERS = 10


async def _timezone(conn: Any, user_id: UUID) -> str:
    tz: str = (
        await conn.execute(select(t.users.c.timezone).where(t.users.c.user_id == user_id))
    ).scalar_one()
    return tz


def _streak(days: set[dt.date], today: dt.date) -> int:
    day = today if today in days else today - dt.timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= dt.timedelta(days=1)
    return n


@router.get("/progress", response_model=ProgressView)
async def get_progress(user_id: CurrentUser, conn: Conn, registry: RegistryDep) -> ProgressView:
    tz = await _timezone(conn, user_id)
    now = dt.datetime.now(dt.UTC)
    today = (await conn.execute(select(func.timezone(tz, func.now())))).scalar_one().date()
    norms = Norms()

    session_days = {
        r[0]
        for r in await conn.execute(
            select(func.date(func.timezone(tz, t.sessions.c.started_at)))
            .where(t.sessions.c.user_id == user_id)
            .distinct()
        )
    }
    rounds = (
        await conn.execute(
            select(t.rounds.c.game_id, t.rounds.c.started_at).where(
                t.rounds.c.user_id == user_id, t.rounds.c.status == "completed"
            )
        )
    ).all()
    states = (
        await conn.execute(
            select(t.dimension_state.c.dim, t.dimension_state.c.n).where(
                t.dimension_state.c.user_id == user_id
            )
        )
    ).all()
    tracked = [d.id for d in registry.dimensions if not d.style]
    stats = StatPills(
        streak_days=_streak(session_days, today),
        rounds_this_week=sum(1 for r in rounds if r.started_at >= now - dt.timedelta(days=7)),
        skills_measured=sum(1 for s in states if s.n > 0 and s.dim in tracked),
        skills_total=len(tracked),
    )

    strips = [
        ContextStrip(label=r.label, start=r.period.lower, end=r.period.upper)
        for r in await conn.execute(
            select(t.life_context).where(t.life_context.c.user_id == user_id)
        )
    ]

    # Skill x week ---------------------------------------------------------------------------
    monday = today - dt.timedelta(days=today.weekday())
    weeks = [monday - dt.timedelta(weeks=WEEKS - 1 - i) for i in range(WEEKS)]
    history = (
        await conn.execute(
            select(t.history).where(t.history.c.user_id == user_id).order_by(t.history.c.day)
        )
    ).all()
    skills = [d for d in tracked if any(h.dim == d for h in history)]
    per_week: dict[tuple[str, dt.date], int] = defaultdict(int)
    for r in rounds:
        week = r.started_at.astimezone(dt.UTC).date()
        week -= dt.timedelta(days=week.weekday())
        for dim in registry.game(r.game_id).primary_dims:
            per_week[(dim, week)] += 1

    def pct(dim: str, mu: float, sigma: float) -> float:
        return norms.percentile(dim, Belief(mu, sigma)).value

    change: list[list[float | None]] = []
    for dim in skills:
        rows = [h for h in history if h.dim == dim]
        line: list[float | None] = []
        for week in weeks:
            end = week + dt.timedelta(days=7)
            inside = [h for h in rows if week <= h.day < end]
            before = [h for h in rows if h.day < week]
            if not inside:
                line.append(None)
                continue
            start_pct = pct(dim, before[-1].mu, before[-1].sigma) if before else 50.0
            line.append(round(pct(dim, inside[-1].mu, inside[-1].sigma) - start_pct, 1))
        change.append(line)
    by_week = SkillWeekHeatmap(
        skills=skills,
        weeks=weeks,
        rounds=[[per_week[(d, w)] for w in weeks] for d in skills],
        change=change,
    )

    # Time of day x weekday ------------------------------------------------------------------
    local = func.timezone(tz, t.trials.c.ts)
    cells = await conn.execute(
        select(
            func.extract("isodow", local).label("dow"),
            func.extract("hour", local).label("hour"),
            func.count().label("n"),
            func.sum(func.cast(t.trials.c.correct, Integer)).label("right"),
        )
        .where(t.trials.c.user_id == user_id, t.trials.c.correct.is_not(None))
        .group_by(text("1"), text("2"))
    )
    answers = [[0] * len(WEEKDAYS) for _ in HOUR_BLOCKS]
    right = [[0] * len(WEEKDAYS) for _ in HOUR_BLOCKS]
    for c in cells:
        block = next(i for i, (lo, hi, _) in enumerate(HOUR_BLOCKS) if lo <= int(c.hour) < hi)
        answers[block][int(c.dow) - 1] += int(c.n)
        right[block][int(c.dow) - 1] += int(c.right or 0)
    by_hour = HourHeatmap(
        weekdays=WEEKDAYS,
        hours=[label for _, _, label in HOUR_BLOCKS],
        accuracy=[
            [
                round(right[b][d] / answers[b][d], 3) if answers[b][d] >= MIN_ANSWERS else None
                for d in range(len(WEEKDAYS))
            ]
            for b in range(len(HOUR_BLOCKS))
        ],
        answers=answers,
        min_answers=MIN_ANSWERS,
    )
    return ProgressView(stats=stats, life_context=strips, by_week=by_week, by_hour=by_hour)


@router.get("/me/decisions", response_model=list[Decision], tags=["sessions"])
async def recent_decisions(
    user_id: CurrentUser, conn: Conn, limit: int = Query(default=20, ge=1, le=100)
) -> list[Decision]:
    rows = await conn.execute(
        select(t.decisions)
        .where(t.decisions.c.user_id == user_id)
        .order_by(t.decisions.c.ts.desc())
        .limit(limit)
    )
    return [
        Decision(
            decision_id=r.decision_id,
            node=r.node,
            at=r.ts,
            question=r.question,
            candidates=[Candidate.model_validate(c) for c in r.candidates],
            chosen=r.chosen,
            reason=r.reason,
            evidence=list(r.evidence),
        )
        for r in rows
    ]


@router.get("/sessions/{session_id}/trace", response_model=list[TraceRow], tags=["sessions"])
async def session_trace(session_id: UUID, user_id: CurrentUser, conn: Conn) -> list[TraceRow]:
    """What each node did in a session and how long it took (docs/plan/03, agent timeline)."""
    rows = (
        await conn.execute(
            select(t.traces.c.node, t.traces.c.event, t.traces.c.ms, t.traces.c.ts)
            .where(t.traces.c.session_id == session_id, t.traces.c.user_id == user_id)
            .order_by(t.traces.c.seq)
        )
    ).all()
    if not rows:
        owner = (
            await conn.execute(
                select(t.sessions.c.user_id).where(t.sessions.c.session_id == session_id)
            )
        ).scalar_one_or_none()
        if owner != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
    return [TraceRow(node=r.node, event=r.event, ms=r.ms, ts=r.ts) for r in rows]


@router.websocket("/twin/stream")
async def twin_stream(websocket: WebSocket) -> None:
    """Pushes {"kind": "twin_updated"} whenever this user's profile changes, from any session or
    device (Postgres NOTIFY from the scored-round transaction). First frame: {"type": "auth",
    "token": ...}."""
    await websocket.accept()
    engine = websocket.app.dependency_overrides.get(engine_dep, engine_dep)()
    try:
        auth = await websocket.receive_json()
        async with engine.begin() as conn:
            user_id = await user_for_token(conn, str(auth.get("token", "")))
        if auth.get("type") != "auth" or user_id is None:
            await websocket.close(code=4401)
            return
        url = libpq_url(engine.url.render_as_string(hide_password=False))
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as listener:
            await listener.execute(f"LISTEN {NOTIFY_CHANNEL}")
            await websocket.send_json({"kind": "ready"})

            async def forward() -> None:
                async for note in listener.notifies():
                    if note.payload == str(user_id):
                        await websocket.send_json({"kind": "twin_updated"})

            async def until_closed() -> None:
                while True:  # the browser sends nothing more; this returns when it leaves
                    await websocket.receive_text()

            tasks = [asyncio.create_task(forward()), asyncio.create_task(until_closed())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                    await task
    except WebSocketDisconnect:
        return
