"""One-tap labels from the user (docs/plan/12): a mood after a round, and "Was I right?" when
Lodestar acted on a frustration guess. They are training labels for the affect model (WP3.3)
and go to the event log only.

Coarse camera and voice cues (WP3.5, WP3.9) arrive here too: one number each, worked out in the
browser. They need their own consent switch and go to the event log only (AGENTS.md rule 3)."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.api.deps import CurrentUser, Engine, RegistryDep
from backend.contracts.affect import CUE_SWITCHES, BiometricCues
from backend.contracts.common import Contract
from backend.contracts.events import AffectBiometricCue, AffectLabelled, AffectLabelPayload
from backend.db import tables as t
from backend.db.consent_store import granted_switches
from backend.db.twin_store import append_event

router = APIRouter(prefix="/affect", tags=["affect"])

ALLOWED = {
    "mood": {"good", "ok", "tough"},
    "was_i_right": {"yes", "no"},
    "rushed": {"rushing", "distracted", "testing"},  # the answer to the red screen
}


class LabelInput(Contract):
    session_id: UUID
    kind: Literal["mood", "was_i_right", "rushed"]
    value: str
    round_id: UUID | None = None
    decision_id: UUID | None = None


class CueInput(BiometricCues):
    session_id: UUID


async def _own_session(conn: AsyncConnection, user_id: UUID, session_id: UUID) -> None:
    owner = (
        await conn.execute(
            select(t.sessions.c.user_id).where(t.sessions.c.session_id == session_id)
        )
    ).scalar_one_or_none()
    if owner != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")


@router.post("/labels", status_code=status.HTTP_204_NO_CONTENT)
async def post_label(body: LabelInput, user_id: CurrentUser, engine: Engine) -> None:
    if body.value not in ALLOWED[body.kind]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {body.kind} value.")
    async with engine.begin() as conn:
        await _own_session(conn, user_id, body.session_id)
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


@router.post("/cues", status_code=status.HTTP_204_NO_CONTENT)
async def post_cues(
    body: CueInput, user_id: CurrentUser, engine: Engine, registry: RegistryDep
) -> None:
    """Each cue needs its own switch (camera, voice tone); a cue whose switch is off is refused.
    Values are rounded to one decimal so only a coarse number is ever kept."""
    sent = {k: v for k, v in body.model_dump(exclude={"session_id"}).items() if v is not None}
    if not sent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No cue sent.")
    async with engine.begin() as conn:
        await _own_session(conn, user_id, body.session_id)
        consent = await granted_switches(conn, user_id, registry.consent)
        off = [CUE_SWITCHES[k] for k in sent if CUE_SWITCHES[k] not in consent]
        if off:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Turn on the {registry.consent.switch(off[0]).title} switch first.",
            )
        await append_event(
            conn,
            AffectBiometricCue(
                user_id=user_id,
                session_id=body.session_id,
                ts=datetime.now(UTC),
                payload=BiometricCues(**{k: round(v, 1) for k, v in sent.items()}),
            ),
        )
