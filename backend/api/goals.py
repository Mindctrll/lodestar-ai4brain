"""Goals and "why" cards (docs/plan/09, 13; UW7, UW11)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.deps import Conn, CurrentUser, RegistryDep
from backend.contracts.decision import Candidate, Decision
from backend.contracts.views import GoalView
from backend.db import tables as t
from backend.db.twin_store import read_twin
from backend.scoring.goals import rounds_to_target
from backend.scoring.kalman_elo import Belief
from backend.scoring.norms import Norms

router = APIRouter(tags=["goals"])


@router.get("/goals", response_model=list[GoalView])
async def get_goals(user_id: CurrentUser, conn: Conn, registry: RegistryDep) -> list[GoalView]:
    norms = Norms()
    twin = await read_twin(conn, user_id, norms=norms)
    views = {v.dim: v for v in twin.dims}
    rows = await conn.execute(
        select(t.goals)
        .where(t.goals.c.user_id == user_id, t.goals.c.status == "active")
        .order_by(t.goals.c.due)
    )
    out = []
    for g in rows:
        view = views.get(g.dim)
        measured = view is not None and view.n > 0
        range_now = (view.percent_high - view.percent_low) / 2 if view and measured else None
        left = (
            rounds_to_target(Belief(view.mu, view.sigma), g.dim, g.target, norms)
            if view and measured
            else None
        )
        out.append(
            GoalView(
                goal_id=g.goal_id,
                dim=g.dim,
                name=registry.dimension(g.dim).name,
                target=g.target,
                due=g.due,
                status=g.status,
                range_now=round(range_now, 1) if range_now is not None else None,
                low=round(view.percent_low, 1) if view and measured else None,
                high=round(view.percent_high, 1) if view and measured else None,
                rounds_left=left,
                met=range_now is not None and range_now <= g.target,
            )
        )
    return out


@router.get("/decisions/{decision_id}", response_model=Decision, tags=["sessions"])
async def get_decision(decision_id: UUID, user_id: CurrentUser, conn: Conn) -> Decision:
    """The card behind a [D1] citation: the question, the top candidates and their parts."""
    row = (
        await conn.execute(
            select(t.decisions).where(
                t.decisions.c.decision_id == decision_id, t.decisions.c.user_id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown decision")
    return Decision(
        decision_id=row.decision_id,
        node=row.node,
        at=row.ts,
        question=row.question,
        candidates=[Candidate.model_validate(c) for c in row.candidates],
        chosen=row.chosen,
        reason=row.reason,
        evidence=list(row.evidence),
    )
