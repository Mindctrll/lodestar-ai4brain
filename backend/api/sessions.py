"""Sessions: start, stream, resume (docs/plan/02 API sketch; 03 streaming).

The browser uses the WebSocket; the CLI and tests use the POST endpoints, which run the graph to
its next pause or end and return the events.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import Field

from backend.agent.runner import SessionNotFound, SessionRunner
from backend.api.deps import CurrentUser, engine_dep
from backend.contracts.common import Contract, Trigger
from backend.db.twin_store import user_for_token

router = APIRouter(prefix="/sessions", tags=["sessions"])


def runner_dep(request: Request) -> SessionRunner:
    runner: SessionRunner = request.app.state.runner
    return runner


Runner = Annotated[SessionRunner, Depends(runner_dep)]


class StartSession(Contract):
    trigger: Trigger = "ui"


class SessionEvents(Contract):
    session_id: UUID
    events: list[dict[str, Any]]


class ResumeInput(Contract):
    value: dict[str, Any]


class MessageInput(Contract):
    text: str = Field(min_length=1, max_length=2000)


async def _collect(
    runner: SessionRunner, user_id: UUID, session_id: UUID, **kw: Any
) -> SessionEvents:
    try:
        events = [e async for e in runner.run(user_id, session_id, **kw)]
    except SessionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from exc
    return SessionEvents(session_id=session_id, events=events)


@router.post("", response_model=SessionEvents, status_code=status.HTTP_201_CREATED)
async def start_session(body: StartSession, user_id: CurrentUser, runner: Runner) -> SessionEvents:
    session_id = await runner.create_session(user_id, body.trigger)
    return await _collect(runner, user_id, session_id)


@router.post("/{session_id}/resume", response_model=SessionEvents)
async def resume_session(
    session_id: UUID, body: ResumeInput, user_id: CurrentUser, runner: Runner
) -> SessionEvents:
    return await _collect(runner, user_id, session_id, resume=body.value)


@router.post("/{session_id}/messages", response_model=SessionEvents)
async def send_message(
    session_id: UUID, body: MessageInput, user_id: CurrentUser, runner: Runner
) -> SessionEvents:
    return await _collect(runner, user_id, session_id, message=body.text)


@router.get("/{session_id}/pending")
async def pending(session_id: UUID, user_id: CurrentUser, runner: Runner) -> dict[str, Any]:
    try:
        return {"pending": await runner.pending(user_id, session_id)}
    except SessionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from exc


class ClientMessage(Contract):
    type: Literal["start", "message", "resume"]
    text: str | None = None
    value: dict[str, Any] | None = None


@router.websocket("/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: UUID) -> None:
    """First frame: {"type": "auth", "token": ...} (browsers can't set headers on a WebSocket).
    Then {"type": "start" | "message" | "resume", ...}; every graph event is sent back."""
    await websocket.accept()
    runner: SessionRunner = websocket.app.state.runner
    engine = websocket.app.dependency_overrides.get(engine_dep, engine_dep)()
    try:
        auth = await websocket.receive_json()
        async with engine.begin() as conn:
            user_id = await user_for_token(conn, str(auth.get("token", "")))
        if auth.get("type") != "auth" or user_id is None:
            await websocket.close(code=4401)
            return
        try:
            waiting = await runner.pending(user_id, session_id)
        except SessionNotFound:
            await websocket.close(code=4404)
            return
        if waiting:
            await websocket.send_json(waiting)
        while True:
            msg = ClientMessage.model_validate(await websocket.receive_json())
            kwargs: dict[str, Any] = {}
            if msg.type == "message":
                kwargs["message"] = msg.text
            elif msg.type == "resume":
                kwargs["resume"] = msg.value
            async for event in runner.run(user_id, session_id, **kwargs):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        return
