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
from backend.contracts.common import Persona
from backend.contracts.events import SessionEnded, SessionEndedPayload
from backend.contracts.facts import (
    CoachReply,
    Fact,
    FactsPacket,
    KnowledgeItem,
    MemoryItem,
)
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.llm.factory import NoModelAvailable
from backend.memory.consolidate import consolidate_user
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
    knowledge: list[KnowledgeItem] = []
    memory = ctx.services.memory
    if memory is not None and summary is not None and summary.changes:
        dim = summary.changes[0].dim
        try:
            tips = await memory.search_knowledge(registry.dimension(dim).plain, dim=dim, limit=1)
        except Exception:  # Qdrant down: coach without a tip
            tips = []
        knowledge = [
            KnowledgeItem(
                id="K1", text=tip.text, source=tip.source, evidence_level=tip.evidence_level
            )
            for tip in tips
        ]
    memories = [MemoryItem(id=f"M{i + 1}", text=m.text) for i, m in enumerate(state.memories[:2])]
    return {"facts": FactsPacket(facts=facts, knowledge=knowledge, memories=memories)}


def template_reply(packet: FactsPacket, persona: str) -> str:
    """Fallback built only from facts: always passes the verifier."""
    picks = [f for f in packet.facts if not f.decision][:3]
    sentences = [f"{f.text} [{f.id}]." for f in picks] or ["Round saved."]
    sentences.append(CLOSING.get(persona, ""))  # type: ignore[call-overload]
    return " ".join(s for s in sentences if s)


MAX_REPAIRS = 2


async def draft_verified(
    ctx: NajmaContext,
    packet: FactsPacket,
    persona: Persona,
    instruction: str,
) -> tuple[str, CoachReply, list[str]]:
    """Draft with the LLM, verify, repair up to twice, else a template built only from facts.
    Nothing reaches the user before it passes (docs/plan/09)."""
    names = [d.name for d in ctx.services.registry.dimensions]
    items: list[Fact | KnowledgeItem | MemoryItem] = [
        *packet.facts,
        *packet.knowledge,
        *packet.memories,
    ]
    listing = "\n".join(f"{i.id}: {i.text}" for i in items)
    messages: list[Any] = [
        SystemMessage(f"{STYLE[persona]}\n{RULES}\n\nFacts:\n{listing}"),
        HumanMessage(instruction),
    ]
    degraded: list[str] = []
    final: str | None = None
    first_ok = False
    repairs = 0
    for attempt in range(1 + MAX_REPAIRS):
        try:
            reply = await ctx.services.llm.generate(ctx.user_id, ctx.llm, messages)
        except NoModelAvailable as exc:
            degraded = exc.degraded
            break
        degraded = list(reply.degraded)
        text = reply.text.strip()
        verdict = verify(text, packet, names, persona)
        if verdict.ok:
            final, first_ok, repairs = text, attempt == 0, attempt
            break
        messages += [
            AIMessage(text),
            HumanMessage(
                "That message broke these rules:\n- "
                + "\n- ".join(verdict.violations[:8])
                + "\nRewrite it so every rule holds. Only the message."
            ),
        ]
        repairs = attempt + 1
    used_template = final is None
    if final is None:
        final = template_reply(packet, persona)
        repairs = min(repairs, MAX_REPAIRS)
    result = verify(final, packet, names, persona)
    reply_model = CoachReply(
        text=final,
        cited_ids=result.cited,
        persona=persona,
        first_draft_passed=first_ok,
        repairs=repairs,
        used_template=used_template,
    )
    return final, reply_model, degraded


@traced("coach")
async def coach(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    packet = state.facts or FactsPacket()
    final, reply_model, degraded = await draft_verified(
        runtime.context, packet, state.persona, "Write the short message shown after this game."
    )
    for sentence in _SENTENCE.split(final):
        emit({"kind": "say", "text": sentence, "node": "coach"})
    emit(
        {
            "kind": "coach",
            "first_draft_passed": reply_model.first_draft_passed,
            "repairs": reply_model.repairs,
            "used_template": reply_model.used_template,
        }
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
    """Score salience and keep what's worth remembering (docs/plan/04, "What gets remembered").
    Routine rounds are not stored in Qdrant; they stay in twin.events."""
    ctx = runtime.context
    store = runtime.store
    if store is None:
        return {}
    registry = ctx.services.registry
    moments: list[tuple[str, str, float, list[str]]] = []  # text, kind, importance, dims
    said = next((m.text for m in reversed(state.messages) if m.type == "human"), "")
    about_self = bool(said) and len(said) > 12 and re.search(r"\b(i|i'm|my|me)\b", said, re.I)
    personal = state.intent and state.intent.kind in ("life_context", "goal", "settings", "chat")
    if about_self and personal:
        moments.append((f'Said: "{said.strip()[:200]}"', "self_statement", 0.9, []))
    last = state.rounds[-1] if state.rounds and state.last_round else None
    if last is not None and last.status == "stopped":
        game = registry.game(last.game_id).name
        moments.append(
            (f"Stopped {game} early ({last.stop_reason or 'no reason'})", "struggle", 0.6, [])
        )
    if state.last_round is not None:
        for change in state.last_round.changes:
            before, _, _ = _pct(ctx, change.dim, change.mu_before, change.sigma_before)
            after, _, _ = _pct(ctx, change.dim, change.mu_after, change.sigma_after)
            if abs(after - before) >= 10:
                name = registry.dimension(change.dim).name
                moments.append(
                    (f"Big change in {name}: {before}% to {after}%", "milestone", 0.6, [change.dim])
                )
    degraded: list[str] = []
    for text, kind, importance, dims in moments:
        key = f"{ctx.session_id}-{len(state.rounds)}-{kind}"
        try:
            await store.aput(
                ("users", str(ctx.user_id), "episodic"),
                key,
                {"text": text, "kind": kind, "importance": importance, "dims": dims},
            )
            emit({"kind": "memory", "text": text})
        except Exception as exc:
            degraded = [f"memory:{type(exc).__name__}->skipped"]
            break
    return {"degraded": degraded} if degraded else {}


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
    services = ctx.services
    if services.memory is None or services.notes is None:
        return {"degraded": ["memory:unavailable->skipped"]}
    games = ", ".join(dict.fromkeys(services.registry.game(r.game_id).name for r in state.rounds))
    highlights = " ".join(f.text + "." for f in (state.facts.facts if state.facts else [])[:2])
    summary = f"Session on {now:%d %b %Y}: played {games or 'no games'}. {highlights}".strip()
    header = [f"Prefers the {state.persona.capitalize()} coach"]
    try:
        await consolidate_user(
            services.memory, services.notes, ctx.user_id, summary=summary, header_lines=header
        )
    except Exception as exc:
        return {"degraded": [f"memory:{type(exc).__name__}->skipped"]}
    return {}
