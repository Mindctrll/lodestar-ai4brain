"""One-tap labels from the user (docs/plan/12): a mood after a round, and "Was I right?" when Najma
acted on a frustration guess. They are training labels for the affect model (WP3.3) and go to
the event log only."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, Engine
from backend.contracts.common import Contract
from backend.contracts.events import AffectLabelled, AffectLabelPayload
from backend.db import tables as t
from backend.db.twin_store import append_event

router = APIRouter(prefix="/affect", tags=["affect"])

ALLOWED = {"mood": {"good", "ok", "tough"}, "was_i_right": {"yes", "no"}}


class LabelInput(Contract):
    session_id: UUID
    kind: Literal["mood", "was_i_right"]
    value: str
    round_id: UUID | None = None
    decision_id: UUID | None = None


@router.post("/labels", status_code=status.HTTP_204_NO_CONTENT)
async def post_label(body: LabelInput, user_id: CurrentUser, engine: Engine) -> None:
    if body.value not in ALLOWED[body.kind]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {body.kind} value.")
    async with engine.begin() as conn:
        owner = (
            await conn.execute(
                select(t.sessions.c.user_id).where(t.sessions.c.session_id == body.session_id)
            )
        ).scalar_one_or_none()
        if owner != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
        await append_event(
            conn,
            AffectLabelled(
                user_id=user_id,
                session_id=body.session_id,
                ts=datetime.now(UTC),
                payload=AffectLabelPayload(
                    kind=body.kind,
                    value=body.value,
                    round_id=body.round_id,
                    decision_id=body.decision_id,
                ),
            ),
        )
