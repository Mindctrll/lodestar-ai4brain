"""Talk to your Twin (docs/plan/09; UW8): the user's practice data answers in first person, only
from facts built for the question, and says how sure it is. When it isn't sure, it offers an
experiment; a "yes" next turn starts one (UW10)."""

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from backend.agent.context import LodestarContext
from backend.agent.nodes.converse import user_timezone
from backend.agent.nodes.talk import draft_verified, emit_reply
from backend.agent.state import LodestarState
from backend.agent.telemetry import record_decision, traced
from backend.agent.twin import (
    TIME_OF_DAY,
    UNKNOWN_CAUSE,
    template_answer,
    time_of_day,
    time_of_day_facts,
)
from backend.contracts.decision import Decision
from backend.contracts.facts import FactsPacket

TWIN_STYLE = (
    "You are the user's Brain Twin: their practice data, speaking in first person ('my games', "
    "'I'). Calm and curious. Say how sure you are. At most 3 sentences."
)


@traced("twin_chat")
async def twin_chat(state: LodestarState, runtime: Runtime[LodestarContext]) -> dict[str, Any]:
    ctx = runtime.context
    text = state.said or ""
    cause = UNKNOWN_CAUSE.search(text)
    if cause and not TIME_OF_DAY.search(text):
        reply = (
            f"I don't know that yet: Lodestar doesn't record {cause.group(1).lower()}. For now I "
            "can test mornings against evenings for you, if you'd like."
        )
        emit_reply(reply, FactsPacket(), "twin")
        await _offer(ctx)
        return {"messages": [AIMessage(reply)]}
    async with ctx.services.engine.connect() as conn:
        tod = await time_of_day(conn, ctx.user_id, await user_timezone(ctx) or "Africa/Tunis")
    packet, refs = time_of_day_facts(tod)
    instruction = (
        f'The user asked: "{text}". Answer as the Twin about when the games go best, from these '
        "facts only, saying how sure you are. If you're not sure, offer a short experiment."
    )
    reply, _, degraded = await draft_verified(
        ctx,
        packet,
        state.persona,
        instruction,
        fallback=template_answer(tod, refs),
        style=TWIN_STYLE,
    )
    emit_reply(reply, packet, "twin")
    if not tod.sure:
        await _offer(ctx)
    update: dict[str, Any] = {"messages": [AIMessage(reply)], "facts": packet}
    if degraded:
        update["degraded"] = degraded
    return update


async def _offer(ctx: LodestarContext) -> None:
    """Remember the offer, so a "yes" next turn starts the experiment."""
    await record_decision(
        ctx,
        Decision(
            decision_id=uuid4(),
            node="twin_offer",
            at=datetime.now(UTC),
            question="Offer an experiment on time of day?",
            candidates=[],
            chosen="time_of_day",
            reason="The Twin wasn't sure whether mornings or evenings go better.",
        ),
    )


AFFIRM = re.compile(
    r"^\s*(twin,?\s*)?(yes|yeah|yep|sure|ok(ay)?|go on|let'?s (do it|test it|try it)|why not|"
    r"sounds good)\b",
    re.I,
)
