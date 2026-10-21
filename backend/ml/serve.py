"""Serving the active models listed in agent.ml_models (docs/plan/10, Files). Nothing here trains;
`predict` uses the same feature code as training."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.contracts.twin import ForecastBand
from backend.db import tables as t
from backend.ml import features
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
