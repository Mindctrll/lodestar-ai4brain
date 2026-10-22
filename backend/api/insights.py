"""Insights, the coach switch and the "under the hood" page (docs/plan/10, 13).

Insights put the models' readings about one person in plain view, each with its range: the
fatigue point, how well their "How sure?" answers match how often they are right, and how
regularly they have played. The engagement-risk score itself is never shown (docs/plan/10,
section 2); only the days played are. The models list is the same for everyone: each active
model with its headline evaluation numbers."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, status
from pydantic import AwareDatetime, Field
from sqlalchemy import Integer, distinct, func, select, update

from backend.api.deps import Conn, CurrentUser, Engine
from backend.contracts.common import Contract, Persona
from backend.contracts.events import SettingsChanged, SettingsChangedPayload
from backend.contracts.twin import FatiguePoint
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.ml.serve import fatigue_now

router = APIRouter(tags=["insights"])

MIN_PROBES = 10  # "How sure?" answers before calibration says anything


class Calibration(Contract):
    said: float = Field(description="Mean confidence given, 0.5 to 1")
    right: float = Field(description="Share of those answers that were right")
    low: float = Field(description="80% range of `right`, Wilson interval")
    high: float
    answers: int


class Rhythm(Contract):
    active_7: int = Field(description="Days played in the last 7 days")
    active_prev_7: int = Field(description="Days played in the 7 days before")
    sessions: int = Field(description="Sessions in all")
    rounds: int = Field(description="Rounds in all")


class InsightsView(Contract):
    fatigue: FatiguePoint | None
    calibration: Calibration | None
    rhythm: Rhythm


class ModelHeadline(Contract):
    label: str
    value: str


class ModelCard(Contract):
    name: str
    title: str
    does: str
    version: str
    trained_at: AwareDatetime
    headline: list[ModelHeadline]


class PersonaInput(Contract):
    persona: Persona


def wilson(right: int, n: int, z: float = 1.2816) -> tuple[float, float]:
    """The 80% Wilson interval for a share."""
    if n == 0:
        return 0.0, 1.0
    p = right / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@router.get("/me/insights", response_model=InsightsView)
async def get_insights(user_id: CurrentUser, conn: Conn, engine: Engine) -> InsightsView:
    probed = (
        await conn.execute(
            select(
                func.count(),
                func.avg(t.trials.c.confidence),
                func.sum(func.cast(t.trials.c.correct, Integer)),
            ).where(
                t.trials.c.user_id == user_id,
                t.trials.c.confidence.is_not(None),
                t.trials.c.correct.is_not(None),
            )
        )
    ).one()
    calibration = None
    if probed[0] >= MIN_PROBES:
        n, right = int(probed[0]), int(probed[2] or 0)
        low, high = wilson(right, n)
        calibration = Calibration(
            said=round(float(probed[1]), 3), right=round(right / n, 3), low=round(low, 3),
            high=round(high, 3), answers=n,
        )  # fmt: skip

    tz = (
        await conn.execute(select(t.users.c.timezone).where(t.users.c.user_id == user_id))
    ).scalar_one_or_none() or "UTC"
    local_day = func.date(func.timezone(tz, t.sessions.c.started_at))
    today = (await conn.execute(select(func.date(func.timezone(tz, func.now()))))).scalar_one()

    async def days_between(start: dt.date, end: dt.date) -> int:
        return int(
            (
                await conn.execute(
                    select(func.count(distinct(local_day))).where(
                        t.sessions.c.user_id == user_id, local_day > start, local_day <= end
                    )
                )
            ).scalar_one()
        )

    week = dt.timedelta(days=7)
    sessions = (
        await conn.execute(
            select(func.count()).select_from(t.sessions).where(t.sessions.c.user_id == user_id)
        )
    ).scalar_one()
    rounds = (
        await conn.execute(
            select(func.count())
            .select_from(t.rounds)
            .where(t.rounds.c.user_id == user_id, t.rounds.c.status == "completed")
        )
    ).scalar_one()
    rhythm = Rhythm(
        active_7=await days_between(today - week, today),
        active_prev_7=await days_between(today - 2 * week, today - week),
        sessions=int(sessions),
        rounds=int(rounds),
    )
    return InsightsView(
        fatigue=await fatigue_now(engine, user_id), calibration=calibration, rhythm=rhythm
    )


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def headline(name: str, metrics: dict[str, Any]) -> tuple[str, str, list[ModelHeadline]]:
    """A title, what the model does, and its evaluation in a few numbers."""
    if name == "growth_forecast":
        one = metrics.get("by_k", {}).get("1", {})
        return (
            "Growth forecast",
            "Predicts where each skill will be after a few more sessions, as an 80% range.",
            [
                ModelHeadline(label="Ranges that held", value=_pct(one.get("coverage", 0))),
                ModelHeadline(label="Target", value="80%"),
                ModelHeadline(label="Error, next session", value=f"{one.get('mae', 0):.2f} SD"),
            ],
        )
    if name == "engagement_risk":
        results = metrics.get("results", {})
        lr = results.get("logistic regression", {})
        rule = results.get("days since last activity (rule)", {})
        return (
            "Engagement risk",
            "Spots when someone may drift away, so Lodestar offers a shorter, easier session.",
            [
                ModelHeadline(label="AUC", value=f"{lr.get('auc', 0):.2f}"),
                ModelHeadline(label="Simple rule's AUC", value=f"{rule.get('auc', 0):.2f}"),
                ModelHeadline(label="Calibration error", value=f"{lr.get('ece', 0):.3f}"),
            ],
        )
    return name.replace("_", " ").capitalize(), "", []


@router.get("/about/models", response_model=list[ModelCard])
async def get_models(user_id: CurrentUser, conn: Conn) -> list[ModelCard]:
    rows = await conn.execute(
        select(t.ml_models).where(t.ml_models.c.active.is_(True)).order_by(t.ml_models.c.name)
    )
    out = []
    for r in rows:
        title, does, numbers = headline(r.name, r.metrics)
        out.append(
            ModelCard(
                name=r.name, title=title, does=does, version=r.version,
                trained_at=r.trained_at, headline=numbers,
            )
        )  # fmt: skip
    return out


@router.put("/me/persona", status_code=status.HTTP_204_NO_CONTENT)
async def set_persona(body: PersonaInput, user_id: CurrentUser, engine: Engine) -> None:
    """Switch coach from the Coach page; the same change as asking in the chat (UW20). Every
    turn reads the coach from the user row, so the next reply uses it."""
    async with engine.begin() as conn:
        await conn.execute(
            update(t.users).where(t.users.c.user_id == user_id).values(persona=body.persona)
        )
        await append_event(
            conn,
            SettingsChanged(
                user_id=user_id,
                ts=dt.datetime.now(dt.UTC),
                payload=SettingsChangedPayload(persona=body.persona),
            ),
        )
