"""Consent, and seeing, editing, exporting and deleting your data (docs/plan/14; UW1, UW14)."""

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field
from sqlalchemy import select

from backend.agent.context import Services
from backend.api.deps import Conn, CurrentUser, Engine, RegistryDep
from backend.contracts.common import ConsentSwitch, Contract
from backend.contracts.llm import LlmSelection
from backend.db import tables as t
from backend.db.consent_store import RequiredSwitch, consent_state, set_consent
from backend.db.llm_store import get_selection, set_selection
from backend.ethics.data_rights import DeletionIncomplete, delete_user, export_user
from backend.registry.models import ConsentNotice

router = APIRouter(tags=["data rights"])


class SwitchView(Contract):
    id: ConsentSwitch
    title: str
    plain: str
    required: bool
    granted: bool


class ConsentView(Contract):
    version: str
    age_minimum: int
    switches: list[SwitchView]


class SwitchInput(Contract):
    granted: bool


class MemoryLine(Contract):
    id: str
    collection: Literal["episodic", "facts"]
    text: str
    kind: str | None = None
    created_at: str | None = None


class LifeContextLine(Contract):
    context_id: UUID
    label: str
    start: str
    end: str


class MyData(Contract):
    core: list[str] = Field(description="Lines of core.md, the short profile Najma keeps")
    life_context: list[LifeContextLine]
    memories: list[MemoryLine]
    memory_available: bool


class Receipt(Contract):
    counts: dict[str, int]
    message: str


def services_of(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def consent_view(notice: ConsentNotice, state: dict[str, bool]) -> ConsentView:
    return ConsentView(
        version=notice.version,
        age_minimum=notice.age_minimum,
        switches=[
            SwitchView(
                id=s.id, title=s.title, plain=s.plain, required=s.required, granted=state[s.id]
            )
            for s in notice.switches
        ],
    )


@router.get("/consent", response_model=ConsentView)
async def get_consent(user_id: CurrentUser, conn: Conn, registry: RegistryDep) -> ConsentView:
    return consent_view(registry.consent, await consent_state(conn, user_id, registry.consent))


@router.put("/consent/{switch}", response_model=ConsentView)
async def put_consent(
    switch: ConsentSwitch,
    body: SwitchInput,
    user_id: CurrentUser,
    engine: Engine,
    registry: RegistryDep,
    request: Request,
) -> ConsentView:
    """Turning a switch off stops that processing at once (docs/plan/14)."""
    notice = registry.consent
    local_model = services_of(request).llm.settings.local_model
    async with engine.begin() as conn:
        try:
            await set_consent(conn, user_id, notice, switch, body.granted)
        except RequiredSwitch as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Core practice data is needed for Najma to work. To stop it, delete your data.",
            ) from exc
        if switch == "cloud_ai" and not body.granted:
            current = await get_selection(conn, user_id, local_model)
            if current.mode == "hosted":
                local = LlmSelection(mode="local", provider="ollama", model=local_model)
                await set_selection(conn, user_id, local)
        state = await consent_state(conn, user_id, notice)
    return consent_view(notice, state)


@router.get("/me/data", response_model=MyData)
async def my_data(user_id: CurrentUser, conn: Conn, request: Request) -> MyData:
    """What the Memory & data screen shows (UW14)."""
    services = services_of(request)
    core = services.notes.read_core(user_id) if services.notes is not None else []
    windows = [
        LifeContextLine(
            context_id=r.context_id,
            label=r.label,
            start=r.period.lower.isoformat(),
            end=r.period.upper.isoformat(),
        )
        for r in await conn.execute(
            select(t.life_context)
            .where(t.life_context.c.user_id == user_id)
            .order_by(t.life_context.c.period.desc())
        )
    ]
    memories: list[MemoryLine] = []
    if services.memory is not None:
        for collection in ("episodic", "facts"):
            for p in await services.memory.points(user_id, collection):
                payload = p.payload or {}
                memories.append(
                    MemoryLine(
                        id=str(p.id),
                        collection=collection,
                        text=str(payload.get("text", "")),
                        kind=payload.get("kind"),
                        created_at=payload.get("created_at"),
                    )
                )
    memories.sort(key=lambda m: m.created_at or "", reverse=True)
    return MyData(
        core=core,
        life_context=windows,
        memories=memories,
        memory_available=services.memory is not None,
    )


class CoreLine(Contract):
    line: str = Field(min_length=1, max_length=500)


async def _forget_text(services: Services, user_id: UUID, text: str) -> None:
    """A line deleted from core.md also goes from the facts collection, and the other way round."""
    if services.notes is not None:
        services.notes.remove_core_line(user_id, text)
    if services.memory is not None:
        same = [
            p.id
            for p in await services.memory.points(user_id, "facts")
            if (p.payload or {}).get("text", "").strip() == text.strip()
        ]
        await services.memory.delete_points(user_id, "facts", same)


@router.post("/me/core/forget", status_code=status.HTTP_204_NO_CONTENT)
async def forget_core_line(body: CoreLine, user_id: CurrentUser, request: Request) -> Response:
    await _forget_text(services_of(request), user_id, body.line)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me/memories/{collection}/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_memory(
    collection: Literal["episodic", "facts"],
    point_id: UUID,
    user_id: CurrentUser,
    request: Request,
) -> Response:
    services = services_of(request)
    if services.memory is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Memory is unavailable right now.")
    point = await services.memory.get(user_id, collection, point_id)  # only this user's points
    if point is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown memory")
    await services.memory.delete_points(user_id, collection, [point_id])
    if collection == "facts":
        await _forget_text(services, user_id, str((point.payload or {}).get("text", "")))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me/life-context/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_life_context(context_id: UUID, user_id: CurrentUser, engine: Engine) -> Response:
    """Removes the window from now on; rounds already scored keep the weight they had."""
    async with engine.begin() as conn:
        result = await conn.execute(
            t.life_context.delete().where(
                t.life_context.c.context_id == context_id, t.life_context.c.user_id == user_id
            )
        )
    if not result.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown entry")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/export")
async def export(user_id: CurrentUser, request: Request) -> Response:
    """A download generated now; nothing is saved on the server."""
    data: dict[str, Any] = await export_user(services_of(request), user_id)
    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="najma-export.json"'},
    )


@router.delete("/me", response_model=Receipt)
async def delete_me(user_id: CurrentUser, request: Request) -> Receipt:
    """Delete everything (the page asks for confirmation first) and return a receipt."""
    runner = request.app.state.runner
    try:
        counts = await delete_user(services_of(request), runner.graph.checkpointer, user_id)
    except DeletionIncomplete as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Couldn't reach the memory store, so nothing was deleted. Please try again.",
        ) from exc
    shown = {
        "events": "events",
        "rounds": "rounds",
        "memories": "memories",
        "sessions": "sessions",
    }
    parts = [f"{counts.get(k, 0):,} {label}" for k, label in shown.items()]
    return Receipt(counts=counts, message="Deleted " + ", ".join(parts) + ".")
