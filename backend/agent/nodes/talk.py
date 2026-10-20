"""Reflect, coach, conversation stubs, remember and consolidate (docs/plan/03, 09).

The coach drafts with the LLM, verifies against the facts packet, and falls back to a template
built only from facts. WP2.4 adds the repair loop; WP2.11 and WP3.2 replace the conversation
stubs; WP1.5 makes `remember` and `consolidate` write memory.
"""

import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from sqlalchemy import select

from backend.agent.context import NajmaContext
from backend.agent.state import NajmaState
from backend.agent.telemetry import emit, traced
from backend.coach.personas import CLOSING, RULES, STYLE
from backend.coach.verify import verify
from backend.contracts.events import SessionEnded, SessionEndedPayload
from backend.contracts.facts import CoachReply, Fact, FactsPacket
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.llm.factory import NoModelAvailable
from backend.scoring.kalman_elo import Belief

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _pct(ctx: NajmaContext, dim: str, mu: float, sigma: float) -> tuple[int, int, int]:
    pr = ctx.services.norms.percentile(dim, Belief(mu=mu, sigma=sigma))
    return round(pr.value), round(pr.low), round(pr.high)


@traced("reflect")
async def reflect(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Build the facts packet from this round's numbers."""
    ctx = runtime.context
    registry = ctx.services.registry
    facts: list[Fact] = []
    summary = state.last_round
    n = 0

    def add(text: str, dim: str | None = None, decision: bool = False, prefix: str = "F") -> None:
        nonlocal n
        n += 1
        facts.append(Fact(id=f"{prefix}{n}", text=text, dim=dim, decision=decision))

    if summary is not None:
        game = registry.game(summary.game_id)
        if summary.answered:
            add(f"You got {summary.correct} of {summary.answered} right in {game.name}")
        for change in summary.changes:
            dim = change.dim
            name = registry.dimension(dim).name
            value, low, high = _pct(ctx, dim, change.mu_after, change.sigma_after)
            add(f"{name} estimate {value}% (80% range {low}-{high}%)", dim)
            before, _, _ = _pct(ctx, dim, change.mu_before, change.sigma_before)
            if before != value:
                add(f"{name} moved from {before}% to {value}%", dim)
            if change.sigma_after < change.sigma_before:
                add(f"I'm more sure about your {name.lower()} than before", dim)
        if summary.quality_verdict not in ("ok", "too_few"):
            add("This round didn't count toward your profile because the answers looked rushed")
    for window in state.context:
        add(f"Life context: {window.label}; today's results count less")
    plan_decisions = [d for d in state.decisions if d.node == "plan_next"]
    if plan_decisions:
        add(plan_decisions[-1].reason, decision=True, prefix="D")
    return {"facts": FactsPacket(facts=facts)}


def template_reply(packet: FactsPacket, persona: str) -> str:
    """Fallback built only from facts: always passes the verifier."""
    picks = [f for f in packet.facts if not f.decision][:3]
    sentences = [f"{f.text} [{f.id}]." for f in picks] or ["Round saved."]
    sentences.append(CLOSING.get(persona, ""))  # type: ignore[call-overload]
    return " ".join(s for s in sentences if s)


@traced("coach")
async def coach(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    ctx = runtime.context
    packet = state.facts or FactsPacket()
    names = [d.name for d in ctx.services.registry.dimensions]
    listing = "\n".join(f"{f.id}: {f.text}" for f in packet.facts)
    messages = [
        SystemMessage(f"{STYLE[state.persona]}\n{RULES}\n\nFacts:\n{listing}"),
        HumanMessage("Write the short message shown after this game."),
    ]
    degraded: list[str] = []
    text: str | None = None
    try:
        reply = await ctx.services.llm.generate(ctx.user_id, ctx.llm, messages)
        text, degraded = reply.text.strip(), list(reply.degraded)
    except NoModelAvailable as exc:
        degraded = exc.degraded
    first_ok = text is not None and verify(text, packet, names).ok
    used_template = not first_ok
    final = text if first_ok and text else template_reply(packet, state.persona)
    result = verify(final, packet, names)
    for sentence in _SENTENCE.split(final):
        emit({"kind": "say", "text": sentence, "node": "coach"})
    reply_model = CoachReply(
        text=final,
        cited_ids=result.cited,
        persona=state.persona,
        first_draft_passed=first_ok,
        repairs=0,
        used_template=used_template,
    )
    return {"reply": reply_model, "messages": [AIMessage(final)], "degraded": degraded}


async def _say(text: str, packet: FactsPacket | None = None) -> dict[str, Any]:
    emit({"kind": "say", "text": text})
    update: dict[str, Any] = {"messages": [AIMessage(text)]}
    if packet is not None:
        update["facts"] = packet
    return update


@traced("converse")
async def converse(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Stand-in until WP2.11: answers 'why' from the latest decision, otherwise points the way."""
    ctx = runtime.context
    text = state.intent.text if state.intent and state.intent.text else ""
    if "why" in text.lower():
        async with ctx.services.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(t.decisions.c.reason)
                    .where(t.decisions.c.user_id == ctx.user_id, t.decisions.c.node == "plan_next")
                    .order_by(t.decisions.c.ts.desc())
                    .limit(1)
                )
            ).one_or_none()
        if row is not None:
            packet = FactsPacket(facts=[Fact(id="D1", text=row.reason, decision=True)])
            return await _say(f"{row.reason} [D1]", packet)
    return await _say("I can explain my choices and your progress. Say 'play' to start a round.")


@traced("twin_chat")
async def twin_chat(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    return await _say("I'm still collecting enough sessions to answer that honestly.")


@traced("experiment")
async def experiment(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    return await _say("Personal experiments are coming soon.")


@traced("update_user")
async def update_user(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    return await _say("Noted. Changing goals and settings by chat is coming soon.")


@traced("respond")
async def respond(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    return {}


@traced("remember")
async def remember(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    # Salience scoring and Qdrant writes arrive with WP1.5.
    return {}


def after_remember(state: NajmaState) -> str:
    if state.verdict in ("end", "break"):
        return "consolidate"
    if (
        state.intent
        and state.intent.kind in ("play", "proactive")
        and state.verdict
        in (
            "continue",
            "ease",
        )
    ):
        return "plan_next"
    return "__end__"


@traced("consolidate")
async def consolidate(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """End-of-session "sleep". WP1.5 adds the journal, dedupe, fact promotion and decay."""
    ctx = runtime.context
    now = datetime.now(UTC)
    minutes = (now - state.started_at).total_seconds() / 60 if state.started_at else 0.0
    reason = {"end": "budget", "break": "break"}.get(state.verdict or "", "user")
    async with ctx.services.engine.begin() as conn:
        await conn.execute(
            t.sessions.update()
            .where(t.sessions.c.session_id == ctx.session_id)
            .values(status="ended", ended_at=now)
        )
        await append_event(
            conn,
            SessionEnded(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                ts=now,
                payload=SessionEndedPayload(
                    reason=reason,
                    rounds=len(state.rounds),
                    minutes=round(minutes, 2),
                ),
            ),
        )
    emit({"kind": "session", "status": "ended", "rounds": len(state.rounds)})
    return {}
