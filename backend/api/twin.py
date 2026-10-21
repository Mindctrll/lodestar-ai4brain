"""Users, trial ingestion and the Brain Twin read model (docs/plan/02, API sketch)."""

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from backend.api.deps import Conn, CurrentUser, Engine
from backend.contracts.common import Contract
from backend.contracts.trial import TrialEvent
from backend.contracts.views import CreatedUser, IngestResult, TwinView
from backend.db.twin_store import ForeignRound, RoundNotFound, create_user, read_twin, record_trials

router = APIRouter()


class TrialBatch(Contract):
    trials: list[TrialEvent] = Field(min_length=1, max_length=500)


@router.post(
    "/users", response_model=CreatedUser, status_code=status.HTTP_201_CREATED, tags=["users"]
)
async def post_user(engine: Engine) -> CreatedUser:
    """Create a user and return their bearer token. WP2.8 adds the age check and consent."""
    async with engine.begin() as conn:
        user_id, token = await create_user(conn)
    return CreatedUser(user_id=user_id, token=token)


@router.post("/events", response_model=IngestResult, tags=["events"])
async def post_events(batch: TrialBatch, user_id: CurrentUser, engine: Engine) -> IngestResult:
    try:
        async with engine.begin() as conn:
            return await record_trials(conn, user_id, batch.trials)
    except RoundNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown round {exc}") from exc
    except ForeignRound as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "That round belongs to someone else"
        ) from exc


@router.get("/twin", response_model=TwinView, tags=["twin"])
async def get_twin(user_id: CurrentUser, conn: Conn) -> TwinView:
    return await read_twin(conn, user_id)
