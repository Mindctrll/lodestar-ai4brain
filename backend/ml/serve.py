"""Serving the active models listed in agent.ml_models (docs/plan/10, Files). Nothing here trains;
`predict` uses the same feature code as training."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.contracts.twin import EngagementReading, FatiguePoint, ForecastBand
from backend.db import tables as t
from backend.ml import fatigue, features
from backend.ml.engagement import FEATURES, EngagementModel, feature_row
from backend.registry.models import Registry

if TYPE_CHECKING:
    import lightgbm as lgb

log = logging.getLogger(__name__)

QUANTILES = (0.1, 0.5, 0.9)
MIN_POINTS = 3  # the model was trained from n >= 3 sessions
MAX_POINTS = 10
SESSIONS_AHEAD = 5


@dataclass(frozen=True)
class GrowthForecaster:
    version: str
    boosters: dict[float, lgb.Booster]
    qhat: dict[int, float]  # conformal widening per horizon k

    @classmethod
    def from_folder(
        cls, folder: str | Path, qhat: dict[Any, float], version: str
    ) -> GrowthForecaster:
        import lightgbm as lgb  # imported here: without its native library, no forecast, no crash

        root = Path(folder)
        boosters = {
            q: lgb.Booster(model_file=str(root / f"q{int(q * 100):02d}.txt")) for q in QUANTILES
        }
        return cls(version, boosters, {int(k): float(v) for k, v in qhat.items()})

    @classmethod
    async def load_active(cls, engine: AsyncEngine) -> GrowthForecaster | None:
        """The active growth model, or None (no model trained yet, or its files are missing):
        the app then shows no forecast rather than a made-up one."""
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        select(t.ml_models).where(
                            t.ml_models.c.name == "growth_forecast", t.ml_models.c.active.is_(True)
                        )
                    )
                ).one_or_none()
            if row is None:
                return None
            return cls.from_folder(row.artefact_path, row.metrics["qhat"], row.version)
        except Exception:
            log.warning("growth forecast unavailable", exc_info=True)
            return None

    def _q(self, k: int) -> float:
        """Calibration for the nearest trained horizon at or above k (wider is the safe side)."""
        ks = sorted(self.qhat)
        return self.qhat[next((x for x in ks if x >= k), ks[-1])]

    def predict(
        self, scores: Sequence[float], gaps: Sequence[float], family: int | None, k: int
    ) -> tuple[float, float, float]:
        """An 80% range for the score k sessions from now, on the population scale."""
        if len(scores) < MIN_POINTS:
            raise ValueError(f"need at least {MIN_POINTS} sessions")
        s = np.asarray(scores[-MAX_POINTS:], dtype=np.float64)[None, :]
        g = np.asarray(gaps[-MAX_POINTS:], dtype=np.float64)[None, :]
        fam = np.array([family if family is not None else -1], dtype=np.float64)
        x = features.build(s, g, np.array([float(k)]), fam)
        last = float(s[0, -1])
        lo, mid, hi = sorted(float(self.boosters[q].predict(x)[0]) + last for q in QUANTILES)
        q = self._q(k)
        return min(lo - q, mid), mid, max(hi + q, mid)


def forecast_bands(
    forecaster: GrowthForecaster,
    registry: Registry,
    history: Sequence[tuple[date, str, float]],
    k: int = SESSIONS_AHEAD,
) -> dict[str, ForecastBand]:
    """Bands per skill from the Brain Twin history: one point per day the skill was practised."""
    by_dim: dict[str, list[tuple[date, float]]] = {}
    for day, dim, mu in sorted(history):
        by_dim.setdefault(dim, []).append((day, mu))
    out: dict[str, ForecastBand] = {}
    for dim, points in by_dim.items():
        if len(points) < MIN_POINTS or not any(d.id == dim for d in registry.dimensions):
            continue
        family = registry.dimension(dim).forecast_family
        scores = [mu for _, mu in points]
        gaps = [0.0] + [1.0] * (len(points) - 1)  # one day of practice = one session
        low, median, high = forecaster.predict(scores, gaps, family, k)
        out[dim] = ForecastBand(
            dim=dim, sessions_ahead=k, low=low, median=median, high=high, source="model"
        )
    return out


async def user_history(engine: AsyncEngine, user_id: UUID) -> list[tuple[date, str, float]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(t.history.c.day, t.history.c.dim, t.history.c.mu).where(
                t.history.c.user_id == user_id
            )
        )
        return [(r.day, r.dim, float(r.mu)) for r in rows]


# Engagement risk and fatigue point (docs/plan/10, sections 2 and 3) ---------------------------

ENGAGEMENT_DAYS = 200
FATIGUE_SESSIONS = 30
BAD_ROUND = ("stopped", "eased")  # Najma's "failures": rounds that went badly


async def load_engagement(engine: AsyncEngine) -> EngagementModel | None:
    """The active engagement model (its numbers live in agent.ml_models), or None."""
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(t.ml_models).where(
                        t.ml_models.c.name == "engagement_risk", t.ml_models.c.active.is_(True)
                    )
                )
            ).one_or_none()
        return None if row is None else EngagementModel.from_metrics(row.version, row.metrics)
    except Exception:
        log.warning("engagement model unavailable", exc_info=True)
        return None


async def activity(
    engine: AsyncEngine, user_id: UUID, today: date, tz: str
) -> tuple[np.ndarray, np.ndarray]:
    """Daily activity (rounds, or 1 for a session without rounds) and bad rounds, oldest first,
    ending today in the user's time zone."""
    start = today - timedelta(days=ENGAGEMENT_DAYS - 1)
    volume = np.zeros(ENGAGEMENT_DAYS)
    fails = np.zeros(ENGAGEMENT_DAYS)
    since = datetime.combine(start - timedelta(days=1), time(), UTC)
    async with engine.connect() as conn:
        r_day = func.date(func.timezone(tz, t.rounds.c.started_at))
        rounds = await conn.execute(
            select(
                r_day.label("day"),
                func.count().label("n"),
                func.count().filter(t.rounds.c.status.in_(BAD_ROUND)).label("bad"),
            )
            .where(t.rounds.c.user_id == user_id, t.rounds.c.started_at >= since)
            .group_by(r_day)
        )
        for r in rounds:
            i = (r.day - start).days
            if 0 <= i < ENGAGEMENT_DAYS:
                volume[i], fails[i] = r.n, r.bad
        s_day = func.date(func.timezone(tz, t.sessions.c.started_at))
        sessions = await conn.execute(
            select(s_day.label("day"))
            .where(t.sessions.c.user_id == user_id, t.sessions.c.started_at >= since)
            .group_by(s_day)
        )
        for r in sessions:
            i = (r.day - start).days
            if 0 <= i < ENGAGEMENT_DAYS:
                volume[i] = max(volume[i], 1.0)
    return volume, fails


async def engagement_reading(
    engine: AsyncEngine, model: EngagementModel, user_id: UUID, tz: str, now: datetime
) -> EngagementReading:
    today = now.astimezone(ZoneInfo(tz)).date()
    volume, fails = await activity(engine, user_id, today, tz)
    volume[-1] = max(volume[-1], 1.0)  # this session is running: today counts
    row = feature_row(volume, fails, ENGAGEMENT_DAYS - 1)
    risk = model.risk(row)
    named = dict(zip(FEATURES, row, strict=True))
    return EngagementReading(
        low=risk.low,
        high=risk.high,
        active_7=int(named["active_7"]),
        active_prev_7=int(named["active_prev_7"]),
        model_version=model.version,
    )


async def fatigue_now(engine: AsyncEngine, user_id: UUID) -> FatiguePoint | None:
    """From the answers of the last sessions: minutes since each session started."""
    async with engine.connect() as conn:
        recent = (
            select(t.sessions.c.session_id)
            .where(t.sessions.c.user_id == user_id)
            .order_by(t.sessions.c.started_at.desc())
            .limit(FATIGUE_SESSIONS)
            .scalar_subquery()
        )
        rows = await conn.execute(
            select(
                t.trials.c.session_id,
                t.trials.c.game_id,
                t.trials.c.ts,
                t.trials.c.rt_ms,
                t.trials.c.correct,
                t.sessions.c.started_at,
            )
            .join(t.sessions, t.sessions.c.session_id == t.trials.c.session_id)
            .where(
                t.trials.c.user_id == user_id,
                t.trials.c.session_id.in_(recent),
                t.trials.c.practice.is_(False),
                t.trials.c.rt_ms.is_not(None),
            )
            .order_by(t.trials.c.ts)
        )
        by_session: dict[UUID, list[fatigue.Answer]] = {}
        for r in rows:
            minute = (r.ts - r.started_at).total_seconds() / 60
            by_session.setdefault(r.session_id, []).append(
                fatigue.Answer(max(minute, 0.0), r.game_id, float(r.rt_ms), r.correct)
            )
    return fatigue.fatigue_point(list(by_session.values()))
