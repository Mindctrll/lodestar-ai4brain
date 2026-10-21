"""Runs the graph for one session and turns LangGraph stream chunks into UI events
(docs/plan/03, "Streaming and the agent timeline").

Thread id = session id, so a session paused at `play` survives refreshes, crashes and restarts:
the next run on that thread resumes it.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StreamMode
from sqlalchemy import func, select

from backend.acs.events import BREAK_MINUTES, Observation
from backend.agent.context import NajmaContext, Services
from backend.agent.state import NajmaState
from backend.contracts.events import SessionStarted, SessionStartedPayload
from backend.db import tables as t
from backend.db.llm_store import get_selection
from backend.db.twin_store import append_event, record_acs

STREAM_MODES: list[StreamMode] = ["updates", "custom"]


class SessionNotFound(LookupError):
    pass


class SessionRunner:
    def __init__(
        self,
        graph: CompiledStateGraph[NajmaState, NajmaContext, Any, Any],
        services: Services,
        local_model: str,
    ) -> None:
        self.graph = graph
        self.services = services
        self.local_model = local_model

    async def create_session(self, user_id: UUID, trigger: str) -> UUID:
        async with self.services.engine.begin() as conn:
            await self._judge_last_break(conn, user_id)
            session_id: UUID = (
                await conn.execute(
                    t.sessions.insert()
                    .values(user_id=user_id, trigger=trigger)
                    .returning(t.sessions.c.session_id)
                )
            ).scalar_one()
            persona = (
                await conn.execute(select(t.users.c.persona).where(t.users.c.user_id == user_id))
            ).scalar_one()
            await append_event(
                conn,
                SessionStarted(
                    user_id=user_id,
                    session_id=session_id,
                    ts=datetime.now(UTC),
                    payload=SessionStartedPayload(trigger=trigger, persona=persona),
                ),
            )
        return session_id

    async def _judge_last_break(self, conn: Any, user_id: UUID) -> None:
        """ACS responsible use: if the last session ended with a suggested break, starting again
        within 10 minutes means the break wasn't taken (docs/plan/11)."""
        last = (
            await conn.execute(
                select(t.sessions.c.session_id, t.sessions.c.ended_at)
                .where(t.sessions.c.user_id == user_id, t.sessions.c.ended_at.is_not(None))
                .order_by(t.sessions.c.started_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if last is None:
            return
        verdict = (
            await conn.execute(
                select(t.decisions.c.chosen)
                .where(t.decisions.c.session_id == last.session_id, t.decisions.c.node == "monitor")
                .order_by(t.decisions.c.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        judged = (
            await conn.execute(
                select(func.count())
                .select_from(t.acs_observations)
                .where(
                    t.acs_observations.c.user_id == user_id,
                    t.acs_observations.c.source == f"break:{last.session_id}",
                )
            )
        ).scalar_one()
        if verdict != "break" or judged:
            return
        now = datetime.now(UTC)
        took_it = (now - last.ended_at).total_seconds() >= BREAK_MINUTES * 60
        obs = Observation("R", took_it, f"break:{last.session_id}")
        await record_acs(conn, user_id, last.session_id, [obs], None, now)

    async def _session(self, user_id: UUID, session_id: UUID) -> tuple[str, str, str]:
        async with self.services.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(t.sessions.c.trigger, t.users.c.persona, t.users.c.success_mode)
                    .join(t.users, t.users.c.user_id == t.sessions.c.user_id)
                    .where(t.sessions.c.session_id == session_id, t.sessions.c.user_id == user_id)
                )
            ).one_or_none()
        if row is None:
            raise SessionNotFound(str(session_id))
        return row.trigger, row.persona, row.success_mode

    async def context_for(self, user_id: UUID, session_id: UUID, seed: int = 0) -> NajmaContext:
        async with self.services.engine.connect() as conn:
            selection = await get_selection(conn, user_id, self.local_model)
            consent = frozenset(
                r.switch
                for r in await conn.execute(
                    select(t.consent.c.switch).where(
                        t.consent.c.user_id == user_id, t.consent.c.granted.is_(True)
                    )
                )
            )
        return NajmaContext(
            user_id=user_id,
            session_id=session_id,
            llm=selection,
            consent=consent,
            services=self.services,
            seed=seed,
        )

    @staticmethod
    def config(session_id: UUID) -> RunnableConfig:
        return {"configurable": {"thread_id": str(session_id)}}

    async def pending(self, user_id: UUID, session_id: UUID) -> dict[str, Any] | None:
        """The exercise a paused session is waiting on, if any (UW6)."""
        await self._session(user_id, session_id)
        snapshot = await self.graph.aget_state(self.config(session_id))
        for intr in snapshot.interrupts:
            return {"kind": "interrupt", "id": intr.id, "payload": intr.value}
        return None

    async def run(
        self,
        user_id: UUID,
        session_id: UUID,
        *,
        message: str | None = None,
        resume: Any = None,
        seed: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        trigger, persona, success_mode = await self._session(user_id, session_id)
        ctx = await self.context_for(user_id, session_id, seed)
        graph_input: Any
        if resume is not None:
            graph_input = Command(resume=resume)
        else:
            graph_input = {
                "user_id": str(user_id),
                "session_id": str(session_id),
                "trigger": trigger,
                "persona": persona,
                "success_mode": success_mode,
                "intent": None,
                "verdict": None,
                "messages": [HumanMessage(message)] if message else [],
            }
        waiting = False
        stream = cast(  # with several stream modes, chunks arrive as (mode, chunk) pairs
            AsyncIterator[tuple[str, Any]],
            self.graph.astream(
                graph_input,
                self.config(session_id),
                context=ctx,
                stream_mode=STREAM_MODES,
                durability="sync",
            ),
        )
        async for mode, chunk in stream:
            if mode == "custom":
                yield chunk
            elif mode == "updates":
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        waiting = True
                        for intr in update:
                            yield {"kind": "interrupt", "id": intr.id, "payload": intr.value}
        yield {"kind": "done", "waiting": waiting}
