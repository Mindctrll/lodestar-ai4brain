"""The converse subgraph (docs/plan/03): pick a tool, ask before writing, use it, answer.

    converse ──(read tool)──────────────► use_tool ─► answer
        │ └──(write tool)─► confirm (pause) ─┘
        └──(small talk, free chat)──────────────────► answer

Each step is its own node so a pause or a crash never repeats a model call or a write. The answer
is fixed text or a coach draft verified against the tool's facts (AGENTS.md rule 4).
"""

import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import func, select

from backend.agent.context import NajmaContext
from backend.agent.nodes.talk import draft_verified, emit_reply
from backend.agent.slots import (
    asks_for_switches,
    due_date,
    history_days,
    life_event,
    local_tz,
    mode_in,
    persona_in,
)
from backend.agent.state import NajmaState
from backend.agent.telemetry import traced
from backend.agent.tools import (
    TOOLS,
    UpdateSettingsArgs,
    estimate_text,
    propose_goal,
    propose_life_context,
    propose_settings,
)
from backend.contracts.facts import Fact, FactsPacket, MemoryItem
from backend.contracts.session import Intent, ToolCall, ToolOutcome
from backend.db import tables as t
from backend.db.twin_store import read_twin

HELP = (
    "I can explain my choices, show how your skills are going, set a goal, or note how your day "
    "is going. Say 'play' to start a round."
)
SMALL_TALK: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^\s*(hi|hello|hey|salam)\b", re.I),
        "Hi! Say 'play' when you're ready, or ask me how your skills are going.",
    ),
    (re.compile(r"^\s*(thanks?|thank (you|u))\b", re.I), "Any time."),
    (
        re.compile(r"\b(who are you|what can you do|how do (the|these) games work)\b", re.I),
        "I'm Najma, a practice coach. I pick short games for the skill I know least about, keep "
        "them hard but doable, and explain every choice. You can also ask how a skill is going, "
        "set a goal, or tell me how your day is.",
    ),
    (
        re.compile(r"^\s*(ok(ay)?|cool|nice|bye|good night)\b", re.I),
        "Okay. I'm here when you want a round.",
    ),
]
SWITCHES = (
    "The camera and microphone switches are in Settings, so you can see exactly what each one "
    "does before you turn it on."
)
WHICH_SKILL = (
    "Which skill would you like a goal for? For example memory, focus, speed or reasoning."
)
WHICH_SETTING = (
    "I can switch your coach (Zitouna, Barq, Hikma or Sahbi) or the difficulty mode (Chill, "
    "Balanced or Push). Which would you like?"
)
DECLINED = "Okay, I've left it as it was."


async def user_timezone(ctx: NajmaContext) -> str | None:
    async with ctx.services.engine.connect() as conn:
        tz: str | None = (
            await conn.execute(select(t.users.c.timezone).where(t.users.c.user_id == ctx.user_id))
        ).scalar_one_or_none()
    return tz


async def exam_day(ctx: NajmaContext, now: datetime) -> date | None:
    """The start of the next exam period the user told Najma about, for "before my exams"."""
    async with ctx.services.engine.connect() as conn:
        start = (
            await conn.execute(
                select(func.min(func.lower(t.life_context.c.period))).where(
                    t.life_context.c.user_id == ctx.user_id,
                    t.life_context.c.label == "exam period",
                    func.lower(t.life_context.c.period) > now,
                )
            )
        ).scalar_one_or_none()
    return start.date() if start is not None else None


async def _profile_facts(ctx: NajmaContext) -> list[Fact]:
    async with ctx.services.engine.connect() as conn:
        twin = await read_twin(conn, ctx.user_id, norms=ctx.services.norms)
    views = sorted((v for v in twin.dims if v.n > 0), key=lambda v: v.percent, reverse=True)
    return [
        Fact(id=f"F{i + 1}", text=estimate_text(ctx, v), dim=v.dim) for i, v in enumerate(views[:5])
    ]


def _call(name: str, args: dict[str, Any], call_id: UUID) -> ToolCall:
    return ToolCall(call_id=call_id, name=name, args=args, writes=TOOLS[name].writes)


async def _free_chat(ctx: NajmaContext, state: NajmaState, text: str) -> ToolOutcome:
    for pattern, reply in SMALL_TALK:
        if pattern.search(text):
            return ToolOutcome(reply=reply)
    memories = [MemoryItem(id=f"M{i + 1}", text=m.text) for i, m in enumerate(state.memories[:2])]
    instruction = (
        f'Reply to this message from the user in at most 3 sentences: "{text}". You are Najma, '
        "a practice coach with short brain games: you explain your picks, show progress, set "
        "goals and note how the user's day is going. If they ask for something else, say kindly "
        "what you can do. Only use a fact if it helps, and cite it."
    )
    packet = FactsPacket(facts=await _profile_facts(ctx), memories=memories)
    return ToolOutcome(facts=packet, instruction=instruction)


@traced("converse")
async def converse(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Choose what to do with a chat, goal, life-context or settings turn."""
    ctx = runtime.context
    intent = state.intent or Intent(kind="chat")
    text = state.said or intent.text or ""
    now = datetime.now(UTC)
    call_id = uuid4()
    call: ToolCall | None = None
    outcome: ToolOutcome | None = None
    if intent.kind == "goal":
        if intent.dim is None:
            outcome = ToolOutcome(reply=WHICH_SKILL)
        else:
            tz = local_tz(await user_timezone(ctx))
            due = due_date(text, now.astimezone(tz).date(), await exam_day(ctx, now))
            call = await propose_goal(ctx, intent.dim, due, call_id)
    elif intent.kind == "life_context":
        tz = local_tz(await user_timezone(ctx))
        event = life_event(text, now, tz)
        if event is None:
            outcome = ToolOutcome(reply="Thanks for telling me.")
        else:
            call = propose_life_context(event, tz, call_id)
    elif intent.kind == "settings":
        args = UpdateSettingsArgs(
            persona=persona_in(text),
            success_mode=mode_in(text),
            pause_dim=intent.avoid_dims[0] if intent.avoid_dims else None,
        )
        if args.persona is None and args.success_mode is None and args.pause_dim is None:
            outcome = ToolOutcome(reply=SWITCHES if asks_for_switches(text) else WHICH_SETTING)
        else:
            call = propose_settings(ctx, args, call_id)
    elif intent.tool == "explain":
        call = _call("explain", {"question": text}, call_id)
    elif intent.tool == "read_profile":
        call = _call("read_profile", {"dim": intent.dim, "question": text}, call_id)
    elif intent.tool == "get_history":
        args_h = {"dim": intent.dim, "days": history_days(text), "question": text}
        call = _call("get_history", args_h, call_id)
    elif intent.tool == "search_memory":
        call = _call("search_memory", {"query": text or "about me"}, call_id)
    else:
        outcome = await _free_chat(ctx, state, text)
    return {"tool_call": call, "confirmed": None, "tool_outcome": outcome}


def after_converse(state: NajmaState) -> str:
    call = state.tool_call
    if call is None:
        return "answer"
    return "confirm" if call.writes else "use_tool"


@traced("confirm")
async def confirm(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Tools that change data ask first (docs/plan/03). Nothing is written before the answer."""
    call = state.tool_call
    assert call is not None
    answer_ = interrupt(
        {
            "type": "confirm",
            "call_id": str(call.call_id),
            "tool": call.name,
            "prompt": call.prompt,
            "facts": call.facts.model_dump(mode="json"),
        }
    )
    ok = isinstance(answer_, dict) and answer_.get("confirmed") is True
    return {"confirmed": ok}


@traced("use_tool")
async def use_tool(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    call = state.tool_call
    assert call is not None
    spec = TOOLS[call.name]
    if spec.writes and state.confirmed is not True:
        return {"tool_outcome": ToolOutcome(name=call.name, reply=DECLINED)}
    outcome, update = await spec.run(runtime.context, state, call)
    return {**update, "tool_outcome": outcome}


@traced("answer")
async def answer(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    outcome = state.tool_outcome or ToolOutcome(reply=HELP)
    packet = outcome.facts
    degraded: list[str] = []
    if outcome.reply is not None:
        text = outcome.reply
    else:
        fallback = outcome.fallback or (HELP if outcome.name is None else None)
        text, _, degraded = await draft_verified(
            runtime.context,
            packet,
            state.persona,
            outcome.instruction or "Answer the user's question from these facts.",
            fallback=fallback,
        )
    emit_reply(text, packet, "answer")
    update: dict[str, Any] = {"messages": [AIMessage(text)], "facts": packet}
    if degraded:
        update["degraded"] = degraded
    return update
