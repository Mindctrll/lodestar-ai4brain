"""Personal experiments (docs/plan/09, 13; UW10): the list with progress and result cards."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from backend.agent.experiments import Comparison, progress, result_facts
from backend.api.deps import Conn, CurrentUser, Engine, RegistryDep
from backend.contracts.views import ExperimentView
from backend.db import tables as t

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("", response_model=list[ExperimentView])
async def list_experiments(
    user_id: CurrentUser, conn: Conn, registry: RegistryDep
) -> list[ExperimentView]:
    rows = await conn.execute(
        select(t.experiments)
        .where(t.experiments.c.user_id == user_id, t.experiments.c.status != "cancelled")
        .order_by(t.experiments.c.created_at.desc())
    )
    out = []
    for row in rows:
        result = row.result or {}
        summary = None
        if "verdict" in result:
            sessions = result["sessions"]
            comparison = Comparison(
                morning=[s["score"] for s in sessions if s["condition"] == "morning"],
                evening=[s["score"] for s in sessions if s["condition"] == "evening"],
                difference=result["difference"],
                low=result["interval"][0],
                high=result["interval"][1],
                p_evening_better=result["p_evening_better"],
                wins=result["wins"],
                pairs=result["pairs"],
            )
            summary = result_facts(comparison)[1]
        out.append(
            ExperimentView(
                exp_id=row.exp_id,
                hypothesis=row.hypothesis,
                status=row.status,
                games=[registry.game(g).name for g in row.design["games"]],
                sessions_per_condition=row.design["sessions_per_condition"],
                progress=progress(row),
                verdict=result.get("verdict"),
                p_evening_better=result.get("p_evening_better"),
                interval=result.get("interval"),
                summary=summary,
                created_at=row.created_at,
            )
        )
    return out


@router.post("/{exp_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(exp_id: UUID, user_id: CurrentUser, engine: Engine) -> None:
    async with engine.begin() as conn:
        done = await conn.execute(
            update(t.experiments)
            .where(
                t.experiments.c.exp_id == exp_id,
                t.experiments.c.user_id == user_id,
                t.experiments.c.status == "running",
            )
            .values(status="cancelled")
        )
    if not done.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No running experiment with that id")
