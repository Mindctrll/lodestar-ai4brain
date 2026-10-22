"""Observability: every node writes to agent.traces, every decision to agent.decisions, and both
stream to the UI's live agent timeline (docs/plan/03, "Streaming", "Observability")."""

import contextlib
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime

from backend.agent.context import LodestarContext
from backend.agent.state import LodestarState
from backend.contracts.decision import Decision
from backend.db import tables as t
from backend.llm.redaction import scrub

log = logging.getLogger(__name__)


class Node(Protocol):
    def __call__(
        self, state: LodestarState, *, runtime: Runtime[LodestarContext]
    ) -> Awaitable[Any]: ...


def emit(event: dict[str, Any]) -> None:
    """Send a custom stream event (decision, node timing, degradation, verified speech)."""
    # Outside a graph run (a unit test calling a node directly) there is no writer.
    with contextlib.suppress(RuntimeError):
        get_stream_writer()(scrub(event))


async def write_trace(
    ctx: LodestarContext,
    node: str,
    event: str,
    ms: float | None = None,
    tokens: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        async with ctx.services.engine.begin() as conn:
            await conn.execute(
                t.traces.insert().values(
                    session_id=ctx.session_id,
                    user_id=ctx.user_id,
                    node=node,
                    event=event,
                    ms=ms,
                    tokens=tokens,
                    payload=scrub(payload) if payload else None,
                )
            )
    except Exception:  # tracing must never break a session
        log.warning("trace write failed for node %s", node, exc_info=True)


async def record_decision(ctx: LodestarContext, decision: Decision) -> None:
    async with ctx.services.engine.begin() as conn:
        await conn.execute(
            t.decisions.insert().values(
                decision_id=decision.decision_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                node=decision.node,
                question=decision.question,
                candidates=[c.model_dump(mode="json") for c in decision.candidates],
                chosen=decision.chosen,
                reason=decision.reason,
                evidence=decision.evidence,
                ts=decision.at,
            )
        )
    emit(
        {
            "kind": "decision",
            "node": decision.node,
            "decision_id": str(decision.decision_id),
            "chosen": decision.chosen,
            "reason": decision.reason,
        }
    )


def traced(
    name: str,
) -> Callable[[Callable[[LodestarState, Runtime[LodestarContext]], Awaitable[Any]]], Node]:
    """Time a node, write its trace row and stream a timeline event."""

    def wrap(fn: Callable[[LodestarState, Runtime[LodestarContext]], Awaitable[Any]]) -> Node:
        @functools.wraps(fn)
        async def run(state: LodestarState, *, runtime: Runtime[LodestarContext]) -> Any:
            start = time.perf_counter()
            emit({"kind": "node", "node": name, "status": "start"})
            try:
                result = await fn(state, runtime)
            except GraphBubbleUp:  # the play pause and other control flow, not failures
                raise
            except Exception as exc:
                ms = (time.perf_counter() - start) * 1000
                await write_trace(
                    runtime.context, name, "error", ms, payload={"error": type(exc).__name__}
                )
                emit({"kind": "node", "node": name, "status": "error", "ms": round(ms, 1)})
                raise
            ms = (time.perf_counter() - start) * 1000
            degraded = result.get("degraded") if isinstance(result, dict) else None
            await write_trace(
                runtime.context,
                name,
                "done",
                ms,
                payload={"degraded": degraded} if degraded else None,
            )
            emit({"kind": "node", "node": name, "status": "done", "ms": round(ms, 1)})
            for step in degraded or []:
                what, _, change = step.partition(":")
                src, _, dst = change.partition("->")
                emit({"kind": "degraded", "what": what, "from": src, "to": dst, "node": name})
            return result

        return run

    return wrap
