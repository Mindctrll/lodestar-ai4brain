"""Ingest, the safety gate and intent routing (docs/plan/03, 09).

The gate and router are rule-based here; WP2.11 adds the small LLM check and structured intent
classification on top, keeping these rules as the fallback.
"""

import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from backend.agent.context import NajmaContext
from backend.agent.state import NajmaState
from backend.agent.telemetry import emit, traced
from backend.contracts.session import Intent

# Requests for a diagnosis or a judgement about a condition (UW13).
DIAGNOSIS = re.compile(
    r"\b(do i have|have i got|am i|could i have|is it|diagnos\w*|test me for|tell me if i have)\b"
    r".{0,60}\b(adhd|add|autis\w*|dyslexi\w*|dyscalculi\w*|dementia|alzheimer\w*|depress\w*|"
    r"anxiety|ocd|bipolar|disorder|condition|deficit|disab\w*|brain damage|something wrong)",
    re.IGNORECASE,
)
CRISIS = re.compile(
    r"\b(kill myself|killing myself|suicid\w*|end my life|self[- ]?harm|hurt myself|want to die|"
    r"don'?t want to live)\b",
    re.IGNORECASE,
)

DIAGNOSIS_REPLY = (
    "I can't tell you that. I only measure practice in these games, not health. "
    "If you're worried, a doctor or psychologist is the right person to ask. "
    "Want to keep practising, or look at what helps focus in these games?"
)
CRISIS_REPLY = (
    "I'm really glad you told me, and I'm pausing the games now. You deserve support from a "
    "person right away. Please talk to someone you trust, or a doctor. If you might be in danger, "
    "call the emergency medical service (SAMU) on 190."
)


def last_text(state: NajmaState) -> str:
    for message in reversed(state.messages):
        if message.type == "human":
            return message.text
    return ""


@traced("ingest")
async def ingest(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if state.started_at is None:
        update["started_at"] = datetime.now(UTC)
    return update


@traced("safety_gate")
async def safety_gate(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    text = last_text(state)
    if CRISIS.search(text):
        return {"intent": Intent(kind="refuse", text="crisis")}
    if DIAGNOSIS.search(text):
        return {"intent": Intent(kind="refuse", text="diagnosis")}
    return {}


def after_safety(state: NajmaState) -> str:
    return "refuse" if state.intent and state.intent.kind == "refuse" else "route_intent"


@traced("refuse")
async def refuse(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """A fixed, kind reply. No LLM free text for this (UW13)."""
    crisis = state.intent is not None and state.intent.text == "crisis"
    reply = CRISIS_REPLY if crisis else DIAGNOSIS_REPLY
    emit({"kind": "say", "text": reply, "template": "crisis" if crisis else "diagnosis"})
    return {"messages": [AIMessage(reply)], "verdict": "end" if crisis else None}


_ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwhy\b", re.I), "chat"),
    (re.compile(r"\b(twin|when am i|am i sharper|my best time)\b", re.I), "twin_chat"),
    (re.compile(r"\bexperiment\b", re.I), "experiment"),
    (re.compile(r"\b(goal|aim for|target)\b", re.I), "goal"),
    (re.compile(r"\b(slept|sleep|exam|tired|sick|busy week)\b", re.I), "life_context"),
    (re.compile(r"\b(setting|persona|coach|voice|camera|mode)\b", re.I), "settings"),
    (re.compile(r"\b(play|game|round|start|train|practi[cs]e|quick|again)\b", re.I), "play"),
]
_THEME = re.compile(r"\babout ([a-z][a-z ]{2,30})$", re.I)


def classify(text: str, trigger: str) -> Intent:
    if not text.strip():
        return Intent(kind="proactive" if trigger in ("schedule", "proactive") else "play")
    for pattern, kind in _ROUTES:
        if pattern.search(text):
            theme = _THEME.search(text.strip().rstrip(".!?"))
            return Intent(
                kind=kind,
                text=text,
                theme=theme.group(1).strip().lower() if theme and kind == "play" else None,
            )
    return Intent(kind="chat", text=text)


@traced("route_intent")
async def route_intent(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    return {"intent": classify(last_text(state), state.trigger), "verdict": None}


def after_route(state: NajmaState) -> str:
    kind = state.intent.kind if state.intent else "play"
    return {
        "play": "plan_next",
        "proactive": "plan_next",
        "chat": "converse",
        "twin_chat": "twin_chat",
        "experiment": "experiment",
    }.get(kind, "update_user")
