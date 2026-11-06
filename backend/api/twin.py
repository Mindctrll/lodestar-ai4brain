"""Users, trial ingestion and the Brain Twin read model (docs/plan/02, API sketch)."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field, field_validator
from sqlalchemy import func, select

from backend.acs.score import score
from backend.agent.nodes.play import formats_by_dim
from backend.agent.patterns import read_patterns
from backend.api.deps import Conn, CurrentUser, Engine, RegistryDep
from backend.contracts.common import ConsentSwitch, Contract, Persona
from backend.contracts.trial import TrialEvent
from backend.contracts.views import (
    AcsComponentView,
    AcsView,
    CreatedUser,
    IngestResult,
    PatternsView,
    TwinView,
)
from backend.db import tables as t
from backend.db.consent_store import granted_switches, set_consent
from backend.db.twin_store import (
    ForeignRound,
    RoundNotFound,
    acs_counts,
    create_user,
    read_twin,
    record_trials,
)

router = APIRouter()


class NewUser(Contract):
    """What the first-visit screens collect (UW1): the age check, the consent switches and the
    coach. Switches left out keep the notice's default."""

    age_confirmed: bool = Field(description="The user confirmed they are 18 or older")
    consent: dict[ConsentSwitch, bool] = Field(default_factory=dict)
    persona: Persona = "willow"
    timezone: str | None = Field(
        default=None, max_length=64, description="IANA time zone from the browser, for 'today'"
    )

    @field_validator("timezone")
    @classmethod
    def _known(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ValueError, KeyError) as exc:
            raise ValueError("unknown time zone") from exc
        return value


class TrialBatch(Contract):
    trials: list[TrialEvent] = Field(min_length=1, max_length=500)


@router.post(
    "/users", response_model=CreatedUser, status_code=status.HTTP_201_CREATED, tags=["users"]
)
async def post_user(body: NewUser, engine: Engine, registry: RegistryDep) -> CreatedUser:
    """Create a user after the age check and consent, and return their bearer token."""
    notice = registry.consent
    if not body.age_confirmed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Lodestar is for people aged {notice.age_minimum} and over in this prototype.",
        )
    if body.consent.get("core") is False:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Core practice data is needed for Lodestar to work.",
        )
    async with engine.begin() as conn:
        user_id, token = await create_user(
            conn, persona=body.persona, timezone=body.timezone, age_confirmed=True
        )
        for switch in notice.switches:
            granted = body.consent.get(switch.id, switch.default)
            await set_consent(conn, user_id, notice, switch.id, granted)
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


@router.get("/me/patterns", response_model=PatternsView, tags=["twin"])
async def get_patterns(
    user_id: CurrentUser, conn: Conn, registry: RegistryDep, request: Request
) -> PatternsView:
    """Skills that have stopped moving, and a split profile's two tracks (docs/plan/07, 13)."""
    consent = await granted_switches(conn, user_id, registry.consent)
    return await read_patterns(
        conn,
        user_id,
        registry,
        request.app.state.services.norms,
        formats_by_dim(registry, consent),
    )


@router.get("/acs", response_model=AcsView, tags=["twin"])
async def get_acs(user_id: CurrentUser, conn: Conn) -> AcsView:
    result = score(await acs_counts(conn, user_id))  # type: ignore[arg-type]  # str keys from SQL
    pushbacks = (
        await conn.execute(
            select(func.count(func.distinct(t.acs_observations.c.round_id))).where(
                t.acs_observations.c.user_id == user_id,
                t.acs_observations.c.source == "pushback",
            )
        )
    ).scalar_one()
    return AcsView(
        pushbacks=int(pushbacks),
        score=result.value,
        low=result.low,
        high=result.high,
        components=[
            AcsComponentView(
                code=c.code,
                name=c.name,
                successes=c.successes,
                opportunities=c.opportunities,
                score=c.mean,
                low=c.low,
                high=c.high,
                weight=c.weight,
                enough_data=c.enough,
            )
            for c in result.components
        ],
    )


@router.get("/twin", response_model=TwinView, tags=["twin"])
async def get_twin(user_id: CurrentUser, conn: Conn) -> TwinView:
    return await read_twin(conn, user_id)
