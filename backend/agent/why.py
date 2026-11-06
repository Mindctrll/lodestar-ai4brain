"""The data behind a pick (docs/plan/09, the "why" audit): lines read from the same numbers as the
progress curves and the time-of-day heatmap, each naming its source. They are stored on the
decision, so an answer about a past pick cites what was true then."""

from datetime import date, datetime, timedelta

from sqlalchemy import Integer, func, select

from backend.agent.context import LodestarContext
from backend.contracts.exercise import WhyLine
from backend.db import tables as t
from backend.scoring.kalman_elo import Belief
from backend.scoring.patterns import HOUR_BLOCKS

PREFIX = "why|"
CURVE_DAYS = 14
MIN_ANSWERS = 8
MIN_RT_CHANGE = 0.03  # smaller than this isn't worth saying


def encode(line: WhyLine) -> str:
    return f"{PREFIX}{line.source}|{line.text}"


def decode(evidence: list[str]) -> list[WhyLine]:
    out = []
    for item in evidence:
        if item.startswith(PREFIX):
            source, _, text = item[len(PREFIX) :].partition("|")
            out.append(WhyLine(source=source, text=text))
    return out


def day_words(day: date, today: date) -> str:
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    return f"on {day.day} {day:%b}"


async def why_lines(ctx: LodestarContext, dim: str, now: datetime) -> list[WhyLine]:
    """Up to three lines: the skill's curve, its response times, and this time of day."""
    registry = ctx.services.registry
    norms = ctx.services.norms
    name = registry.dimension(dim).name
    games = [g.id for g in registry.games if dim in g.dims]
    lines: list[WhyLine] = []
    async with ctx.services.engine.connect() as conn:
        tz = (
            await conn.execute(select(t.users.c.timezone).where(t.users.c.user_id == ctx.user_id))
        ).scalar_one_or_none() or "UTC"
        today = (await conn.execute(select(func.date(func.timezone(tz, func.now()))))).scalar_one()

        rows = (
            await conn.execute(
                select(t.history.c.day, t.history.c.mu, t.history.c.sigma)
                .where(
                    t.history.c.user_id == ctx.user_id,
                    t.history.c.dim == dim,
                    t.history.c.day >= today - timedelta(days=CURVE_DAYS),
                )
                .order_by(t.history.c.day)
            )
        ).all()
        if len(rows) >= 2:
            a = norms.percentile(dim, Belief(rows[0].mu, rows[0].sigma))
            b = norms.percentile(dim, Belief(rows[-1].mu, rows[-1].sigma))
            days = (rows[-1].day - rows[0].day).days
            lines.append(
                WhyLine(
                    source="Progress curve",
                    text=f"{name} went from {round(a.value)}% (likely {round(a.low)}-"
                    f"{round(a.high)}%) to {round(b.value)}% (likely {round(b.low)}-"
                    f"{round(b.high)}%) over {days} days",
                )
            )

        local_day = func.date(func.timezone(tz, t.trials.c.ts))
        speeds = (
            await conn.execute(
                select(local_day.label("day"), func.avg(t.trials.c.rt_ms).label("rt"))
                .where(
                    t.trials.c.user_id == ctx.user_id,
                    t.trials.c.game_id.in_(games),
                    t.trials.c.practice.is_(False),
                    t.trials.c.rt_ms.is_not(None),
                )
                .group_by(local_day)
                .having(func.count() >= MIN_ANSWERS)
                .order_by(local_day.desc())
                .limit(2)
            )
        ).all()
        if len(speeds) == 2 and speeds[1].rt:
            change = float(speeds[0].rt) / float(speeds[1].rt) - 1
            if abs(change) >= MIN_RT_CHANGE:
                way = "slower" if change > 0 else "faster"
                lines.append(
                    WhyLine(
                        source="Response time",
                        text=f"Your {name.lower()} answers were {abs(round(change * 100))}% {way} "
                        f"{day_words(speeds[0].day, today)} than the time before",
                    )
                )

        hour = int(
            (
                await conn.execute(select(func.extract("hour", func.timezone(tz, func.now()))))
            ).scalar_one()
        )
        low, high, label = next(b for b in HOUR_BLOCKS if b[0] <= hour < b[1])
        local_hour = func.extract("hour", func.timezone(tz, t.trials.c.ts))
        cell = (
            await conn.execute(
                select(func.count(), func.sum(func.cast(t.trials.c.correct, Integer))).where(
                    t.trials.c.user_id == ctx.user_id,
                    t.trials.c.correct.is_not(None),
                    local_hour >= low,
                    local_hour < high,
                )
            )
        ).one()
        if cell[0] >= MIN_ANSWERS:
            when = "at night" if label == "night" else f"between {low}:00 and {high}:00"
            lines.append(
                WhyLine(
                    source="Time-of-day heatmap",
                    text=f"You get {round(100 * int(cell[1] or 0) / int(cell[0]))}% right {when} "
                    f"({int(cell[0])} answers)",
                )
            )
    return lines
