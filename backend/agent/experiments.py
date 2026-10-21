"""Personal experiments (docs/plan/09, "Personal experiments"; UW10).

For now one kind: does this person do better in the morning or in the evening? The design is a
few sessions in each window with the same games; each session is tagged by its local start time,
scored by the mean round score of those games, and the two windows are compared with a Bayesian
difference in means. The result says how sure it is, and says "inconclusive" when it isn't.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.contracts.events import (
    ExperimentCompleted,
    ExperimentPayload,
    ExperimentSessionLogged,
    ExperimentStarted,
)
from backend.contracts.facts import Fact, FactsPacket
from backend.db import tables as t
from backend.db.twin_store import append_event

WINDOWS: dict[str, tuple[int, int]] = {"morning": (5, 12), "evening": (18, 24)}
SESSIONS_PER_WINDOW = 3
SURE = 0.8  # report a winner only when P(one window is better) >= 0.8


def window_of(local_hour: int) -> str | None:
    for name, (start, end) in WINDOWS.items():
        if start <= local_hour < end:
            return name
    return None


def design(games: list[str], dim: str | None) -> dict[str, Any]:
    return {
        "kind": "time_of_day",
        "conditions": list(WINDOWS),
        "windows": {k: list(v) for k, v in WINDOWS.items()},
        "sessions_per_condition": SESSIONS_PER_WINDOW,
        "games": games,
        "dim": dim,
    }


@dataclass(frozen=True)
class Comparison:
    morning: list[float]
    evening: list[float]
    difference: float  # evening minus morning, mean round score
    low: float  # 80% credible interval
    high: float
    p_evening_better: float
    wins: int  # evening-vs-morning session pairs that evening won
    pairs: int

    @property
    def verdict(self) -> str:
        if self.p_evening_better >= SURE:
            return "evening"
        if self.p_evening_better <= 1 - SURE:
            return "morning"
        return "inconclusive"


def compare(morning: list[float], evening: list[float]) -> Comparison:
    """Difference in means with a flat prior and the pooled variance: the posterior of the
    difference is a t distribution, approximated as normal for these small tables (and widened
    a little by never letting the spread fall below 0.05)."""
    m, e = np.array(morning, dtype=float), np.array(evening, dtype=float)
    diff = float(e.mean() - m.mean())
    pooled = float(
        np.sqrt(
            ((m.var(ddof=1) if len(m) > 1 else 0.01) + (e.var(ddof=1) if len(e) > 1 else 0.01)) / 2
        )
    )
    se = max(pooled, 0.05) * math.sqrt(1 / len(m) + 1 / len(e))
    p = 0.5 * (1 + math.erf(diff / (se * math.sqrt(2))))
    wins = sum(1 for a in e for b in m if a > b)
    return Comparison(
        morning=list(map(float, m)),
        evening=list(map(float, e)),
        difference=diff,
        low=diff - 1.2816 * se,
        high=diff + 1.2816 * se,
        p_evening_better=p,
        wins=wins,
        pairs=len(e) * len(m),
    )


async def running(conn: AsyncConnection, user_id: UUID) -> Any | None:
    return (
        await conn.execute(
            select(t.experiments).where(
                t.experiments.c.user_id == user_id, t.experiments.c.status == "running"
            )
        )
    ).one_or_none()


async def start(
    conn: AsyncConnection, user_id: UUID, session_id: UUID, exp_id: UUID, hypothesis: str,
    plan: dict[str, Any],
) -> None:  # fmt: skip
    exists = (
        await conn.execute(select(t.experiments.c.exp_id).where(t.experiments.c.exp_id == exp_id))
    ).scalar_one_or_none()
    if exists is not None:  # a re-run after a crash must not start it twice
        return
    await conn.execute(
        update(t.experiments)
        .where(t.experiments.c.user_id == user_id, t.experiments.c.status == "running")
        .values(status="cancelled", updated_at=datetime.now(UTC))
    )
    await conn.execute(
        t.experiments.insert().values(
            exp_id=exp_id, user_id=user_id, hypothesis=hypothesis, design=plan,
            status="running", result={"sessions": []},
        )
    )  # fmt: skip
    await append_event(
        conn,
        ExperimentStarted(
            user_id=user_id, session_id=session_id, ts=datetime.now(UTC),
            payload=ExperimentPayload(exp_id=exp_id, hypothesis=hypothesis),
        ),
    )  # fmt: skip


def progress(row: Any) -> dict[str, int]:
    sessions = (row.result or {}).get("sessions", [])
    return {c: sum(1 for s in sessions if s["condition"] == c) for c in row.design["conditions"]}


async def log_session(
    conn: AsyncConnection, row: Any, user_id: UUID, session_id: UUID, condition: str, score: float
) -> Comparison | None:
    """Record one finished experiment session; when every window has its sessions, compare and
    close the experiment. Returns the comparison when it closed."""
    sessions = list((row.result or {}).get("sessions", []))
    if any(s["session_id"] == str(session_id) for s in sessions):
        return None
    sessions.append({"session_id": str(session_id), "condition": condition, "score": score})
    now = datetime.now(UTC)
    await append_event(
        conn,
        ExperimentSessionLogged(
            user_id=user_id, session_id=session_id, ts=now,
            payload=ExperimentPayload(
                exp_id=row.exp_id, condition=condition, result={"score": round(score, 4)}
            ),
        ),
    )  # fmt: skip
    need = row.design["sessions_per_condition"]
    counts = {c: sum(1 for s in sessions if s["condition"] == c) for c in row.design["conditions"]}
    result: dict[str, Any] = {"sessions": sessions}
    status = "running"
    comparison = None
    if all(n >= need for n in counts.values()):
        comparison = compare(
            [s["score"] for s in sessions if s["condition"] == "morning"],
            [s["score"] for s in sessions if s["condition"] == "evening"],
        )
        verdict = comparison.verdict
        status = "inconclusive" if verdict == "inconclusive" else "completed"
        result |= {
            "verdict": verdict,
            "p_evening_better": round(comparison.p_evening_better, 3),
            "difference": round(comparison.difference, 4),
            "interval": [round(comparison.low, 4), round(comparison.high, 4)],
            "wins": comparison.wins,
            "pairs": comparison.pairs,
        }
        await append_event(
            conn,
            ExperimentCompleted(
                user_id=user_id, session_id=session_id, ts=now,
                payload=ExperimentPayload(exp_id=row.exp_id, result=result),
            ),
        )  # fmt: skip
    await conn.execute(
        update(t.experiments)
        .where(t.experiments.c.exp_id == row.exp_id)
        .values(result=result, status=status, updated_at=now)
    )
    return comparison


def result_facts(comparison: Comparison) -> tuple[FactsPacket, str]:
    """The result card's facts, and a reply that cites them (every number from a fact)."""
    better = comparison.verdict
    p_better = (
        comparison.p_evening_better if better != "morning" else 1 - comparison.p_evening_better
    )
    morning = sum(comparison.morning) / len(comparison.morning)
    evening = sum(comparison.evening) / len(comparison.evening)
    facts = [
        Fact(id="F1", text=f"Morning sessions averaged {round(morning * 100)}%, evening sessions "
             f"{round(evening * 100)}%"),
        Fact(id="F2", text=f"Probability evening is better: {comparison.p_evening_better:.2f}"),
    ]  # fmt: skip
    if better == "inconclusive":
        text = (
            "The experiment is done, and it's inconclusive [F1]: morning and evening came out too "
            "close to tell apart [F2]. I'll keep suggesting both."
        )
        return FactsPacket(facts=facts), text
    wins = comparison.wins if better == "evening" else comparison.pairs - comparison.wins
    facts.append(
        Fact(
            id="F3",
            text=f"{better.capitalize()} was better in {wins} of {comparison.pairs} comparisons, "
            f"probability {p_better:.2f}",
        )
    )
    text = (
        f"Experiment done: {better} was better in {wins} of {comparison.pairs} comparisons "
        f"[F3]. Probability {better} is better: {p_better:.2f} [F3]. I'll suggest {better} "
        "sessions from now on."
    )
    return FactsPacket(facts=facts), text
