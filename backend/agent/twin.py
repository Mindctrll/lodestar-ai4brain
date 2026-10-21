"""What the Twin knows about patterns (docs/plan/09, "Talk to your Twin"; UW8).

The Twin speaks in first person, but only from facts built here for the question: accuracy by
time of day in the user's own time zone, with how many sessions it rests on and how sure that is.
"""

import re
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.agent.experiments import WINDOWS
from backend.contracts.facts import Fact, FactsPacket
from backend.db import tables as t

TIME_OF_DAY = re.compile(
    r"\b(sharpest|best time|time of day|morning|evening|night|afternoon|when am i|"
    r"when do i)\b",
    re.I,
)
UNKNOWN_CAUSE = re.compile(r"\b(coffee|caffeine|music|tea|sleep|exercise|breakfast)\b", re.I)
MIN_ANSWERS = 30  # per window, before comparing
SURE = 0.9
FEW_SESSIONS = 15


@dataclass(frozen=True)
class WindowStats:
    name: str
    right: int
    answers: int
    sessions: int

    @property
    def accuracy(self) -> float:
        return self.right / self.answers if self.answers else 0.0


@dataclass(frozen=True)
class TimeOfDay:
    windows: list[WindowStats]
    best: str | None
    worst: str | None
    p_best: float  # probability the best window is really better than the worst
    sessions: int

    @property
    def sure(self) -> bool:
        return self.best is not None and self.p_best >= SURE and self.sessions >= FEW_SESSIONS


async def time_of_day(conn: AsyncConnection, user_id: UUID, tz: str) -> TimeOfDay:
    local = func.timezone(tz, t.trials.c.ts)
    hour = func.extract("hour", local)
    rows = await conn.execute(
        select(
            hour.label("hour"),
            func.count().label("n"),
            func.sum(func.cast(t.trials.c.correct, Integer)).label("right"),
            func.count(func.distinct(t.trials.c.session_id)).label("sessions"),
        )
        .where(t.trials.c.user_id == user_id, t.trials.c.correct.is_not(None))
        .group_by(hour)
    )
    acc: dict[str, list[int]] = {name: [0, 0, 0] for name in WINDOWS}
    total_sessions = (
        await conn.execute(
            select(func.count(func.distinct(t.trials.c.session_id))).where(
                t.trials.c.user_id == user_id
            )
        )
    ).scalar_one()
    for r in rows:
        for name, (start, end) in WINDOWS.items():
            if start <= int(r.hour) < end:
                acc[name][0] += int(r.right or 0)
                acc[name][1] += int(r.n)
                acc[name][2] += int(r.sessions)
    windows = [WindowStats(name, *acc[name]) for name in WINDOWS]
    usable = [w for w in windows if w.answers >= MIN_ANSWERS]
    if len(usable) < 2:
        return TimeOfDay(windows, None, None, 0.5, int(total_sessions))
    best = max(usable, key=lambda w: w.accuracy)
    worst = min(usable, key=lambda w: w.accuracy)
    rng = np.random.default_rng(0)  # same answer for the same data
    a = rng.beta(best.right + 1, best.answers - best.right + 1, 20_000)
    b = rng.beta(worst.right + 1, worst.answers - worst.right + 1, 20_000)
    return TimeOfDay(windows, best.name, worst.name, float(np.mean(a > b)), int(total_sessions))


def time_of_day_facts(tod: TimeOfDay) -> tuple[FactsPacket, dict[str, str]]:
    """The facts, and which fact id holds each window, the probability and the session count."""
    facts: list[Fact] = []
    refs: dict[str, str] = {}

    def add(key: str, text: str) -> None:
        refs[key] = f"F{len(facts) + 1}"
        facts.append(Fact(id=refs[key], text=text))

    for w in tod.windows:
        if w.answers:
            add(
                w.name,
                f"In the {w.name} my games go {round(w.accuracy * 100)}% right "
                f"({w.answers} answers over {w.sessions} sessions)",
            )
    if tod.best and tod.worst and tod.best != tod.worst:
        add(
            "p",
            f"Probability that the {tod.best} is really better than the {tod.worst}: "
            f"{tod.p_best:.2f}",
        )
    add("sessions", f"I have {tod.sessions} sessions so far")
    return FactsPacket(facts=facts), refs


def template_answer(tod: TimeOfDay, refs: dict[str, str]) -> str:
    """A first-person reply built only from the facts (used when no draft passes)."""
    if tod.best is None or tod.worst is None:
        return (
            "I haven't seen enough morning and evening play to compare them yet "
            f"[{refs['sessions']}]. Play at different times and I'll tell you."
        )
    text = (
        f"My games go best in the {tod.best} [{refs[tod.best]}] and least well in the "
        f"{tod.worst} [{refs[tod.worst]}]. The chance the {tod.best} is really better is "
        f"{tod.p_best:.2f} [{refs['p']}]."
    )
    if not tod.sure:
        text += (
            f" With {tod.sessions} sessions I'm not sure yet [{refs['sessions']}]. "
            "Want to test it with a short experiment?"
        )
    return text
