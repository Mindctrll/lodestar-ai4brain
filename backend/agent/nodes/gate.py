"""Ingest, the safety gate and intent routing (docs/plan/03, 09).

Both the gate and the router are rules first, with a small structured model call on top: the gate
asks a model only when a message touches on health and no rule fired; the router only when its
rules aren't sure (backend/agent/intents.py). Without a model, the rules decide.
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from pydantic import Field
from sqlalchemy import select

from backend.agent.context import NajmaContext
from backend.agent.intents import route
from backend.agent.nodes.twin import AFFIRM
from backend.agent.state import NajmaState
from backend.agent.telemetry import emit, traced
from backend.contracts.common import Contract
from backend.contracts.session import Intent
from backend.db import tables as t
from backend.llm.factory import NoModelAvailable

# Requests for a diagnosis or a judgement about a condition (UW13). Naming a condition is enough;
# vaguer words ("condition", "normal", "wrong with me") need a question about oneself.
CONDITIONS = re.compile(
    r"\b(adhd|autis\w*|asperger\w*|on the spectrum|dyslexi\w*|dyscalculi\w*|dyspraxi\w*|"
    r"dementia|alzheimer\w*|bipolar|ocd|ptsd|schizophreni\w*|depress(ed|ion)|"
    r"(learning|intellectual) disab\w*|attention deficit|brain damage|mental illness|"
    r"disorder\w*|diagnos\w*)\b|(?-i:\bADD\b)",
    re.IGNORECASE,
)
DIAGNOSIS = re.compile(
    r"\b(do i have|have i got|could i (have|be)|am i|might (this|it) be|could (this|it) be|"
    r"what|is (it|this)) .{0,40}\b(condition|deficit|disab\w*|anxiety)\b"
    r"|\b(something|what'?s|what is) (is )?wrong with (me|my)\b"
    r"|\bis my (brain|memory|focus|attention|mind) (normal|ok|okay|healthy)\b"
    r"|\bmy \w+ normal for my age\b",
    re.IGNORECASE,
)
MEDICAL = re.compile(
    r"\b(should i take|can i take|how much \w+ should i take|medication|medicine|pills?|"
    r"supplements?|nootropics?|melatonin|ritalin|adderall|modafinil|dos(e|age)|prescri\w*)\b",
    re.IGNORECASE,
)
CRISIS = re.compile(
    r"\b(kill myself|killing myself|suicid\w*|end my life|self[- ]?harm|hurt(ing)? myself|"
    r"want to die|don'?t want to live|point (of|in) living|better off dead)\b",
    re.IGNORECASE,
)
# Words that make a small model check worth its latency when no rule fired.
HEALTH_CUES = re.compile(
    r"\b(doctor|health|mental|brain|normal|wrong with|worried|scared|hopeless|worthless|"
    r"give up|alone|cope|coping|panic|drug|caffeine|coffee|sleeping)\b",
    re.IGNORECASE,
)

DIAGNOSIS_REPLY = (
    "I can't tell you that. I only measure practice in these games, not health. "
    "If you're worried, a doctor or psychologist is the right person to ask. "
    "Want to keep practising, or look at what helps focus in these games?"
)
MEDICAL_REPLY = (
    "I can't give advice about medicines or supplements. I only measure practice in these "
    "games. A doctor or pharmacist is the right person to ask. Want to keep practising?"
)
CRISIS_REPLY = (
    "I'm really glad you told me, and I'm pausing the games now. You deserve support from a "
    "person right away. Please talk to someone you trust, or a doctor. If you might be in danger, "
    "call the emergency medical service (SAMU) on 190."
)
REPLIES = {"diagnosis": DIAGNOSIS_REPLY, "medical": MEDICAL_REPLY, "crisis": CRISIS_REPLY}


def screen(text: str) -> str | None:
    """The rules: 'crisis', 'diagnosis', 'medical' or None. Crisis is checked first."""
    if CRISIS.search(text):
        return "crisis"
    if CONDITIONS.search(text) or DIAGNOSIS.search(text):
        return "diagnosis"
    if MEDICAL.search(text):
        return "medical"
    return None


class SafetyCheck(Contract):
    kind: Literal["none", "diagnosis", "medical", "crisis"] = Field(
        description="diagnosis: asks whether they have a health condition; medical: asks about "
        "medicines, supplements or doses; crisis: talks about wanting to die or self-harm"
    )


SAFETY_PROMPT = (
    "You check messages sent to a practice coach with brain games. Reply with JSON. "
    'kind = "crisis" if the person talks about wanting to die or harming themselves, '
    '"diagnosis" if they ask whether they have a health condition, "medical" if they ask about '
    'medicines, supplements or doses, otherwise "none". Being stressed about exams, tired, or '
    'joking about a hard game is "none". Reply with only {"kind": "..."}.'
)


@traced("ingest")
async def ingest(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if state.started_at is None:
        update["started_at"] = datetime.now(UTC)
    return update


@traced("safety_gate")
async def safety_gate(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Rules first. When none fires but the message touches on health, a small structured model
    check may still stop it; the model can only add a refusal, never lift one."""
    text = state.said or ""
    kind = screen(text)
    degraded: list[str] = []
    if kind is None and HEALTH_CUES.search(text):
        ctx = runtime.context
        messages = [SystemMessage(SAFETY_PROMPT), HumanMessage(text)]
        try:
            check = await ctx.services.llm.structured(ctx.user_id, ctx.llm, messages, SafetyCheck)
            degraded = list(check.degraded)
            kind = None if check.value.kind == "none" else check.value.kind
        except NoModelAvailable as exc:
            degraded = [*exc.degraded, "safety:llm->rules"]
    update: dict[str, Any] = {"degraded": degraded} if degraded else {}
    if kind is not None:
        update["intent"] = Intent(kind="refuse", text=kind)
    return update


def after_refuse(state: NajmaState) -> str:
    crisis = state.intent is not None and state.intent.text == "crisis"
    return "play" if state.game_waiting() and not crisis else "__end__"


def after_safety(state: NajmaState) -> str:
    return "refuse" if state.intent and state.intent.kind == "refuse" else "route_intent"


@traced("refuse")
async def refuse(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """A fixed, kind reply. No LLM free text for this (UW13)."""
    kind = state.intent.text if state.intent and state.intent.text in REPLIES else "diagnosis"
    reply = REPLIES[kind]
    emit({"kind": "say", "text": reply, "template": kind})
    return {"messages": [AIMessage(reply)], "verdict": "end" if kind == "crisis" else None}


@traced("route_intent")
async def route_intent(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Rules first; when they aren't sure, one structured model call. Code still decides what
    happens next: the model only fills in the intent."""
    ctx = runtime.context
    text = state.said or ""
    intent, degraded = await route(
        text, state.trigger, ctx.services.registry, ctx.services.llm, ctx.user_id, ctx.llm
    )
    if intent.kind in ("chat", "play", "twin_chat") and AFFIRM.search(text) and await _offered(ctx):
        # "Yes" right after the Twin offered an experiment (UW8 to UW10).
        intent = Intent(kind="experiment", text="time of day")
    if intent.kind == "settings" and not intent.avoid_dims and _IT.search(text):
        # "stop suggesting it" right after Najma asked about a skill the user keeps skipping.
        nudged = await _last_nudge(ctx)
        if nudged is not None:
            intent = intent.model_copy(update={"avoid_dims": [nudged]})
    # The UI opens the matching surface (the Twin, goals, experiments) beside the reply.
    emit({"kind": "intent", "intent": intent.kind, "dim": intent.dim, "tool": intent.tool})
    update: dict[str, Any] = {"intent": intent, "verdict": None}
    if degraded:
        update["degraded"] = degraded
    return update


_IT = re.compile(r"\b(stop suggesting|don'?t suggest) (it|that|them)\b", re.IGNORECASE)


async def _offered(ctx: NajmaContext) -> bool:
    """The last thing decided this session was the Twin's experiment offer."""
    async with ctx.services.engine.connect() as conn:
        node = (
            await conn.execute(
                select(t.decisions.c.node)
                .where(t.decisions.c.session_id == ctx.session_id)
                .order_by(t.decisions.c.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return node == "twin_offer"


async def _last_nudge(ctx: NajmaContext) -> str | None:
    async with ctx.services.engine.connect() as conn:
        chosen = (
            await conn.execute(
                select(t.decisions.c.chosen)
                .where(t.decisions.c.session_id == ctx.session_id, t.decisions.c.node == "nudge")
                .order_by(t.decisions.c.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return chosen


def after_route(state: NajmaState) -> str:
    kind = state.intent.kind if state.intent else "play"
    return {
        "play": "plan_next",
        "proactive": "plan_next",
        "twin_chat": "twin_chat",
    }.get(kind, "converse")
