"""Intent routing (docs/plan/03, route_intent): keyword rules first, a structured LLM call only when
the rules aren't sure. The rules are also the fallback when no model answers in time.

Slots are filled here too: a game or skill the user named, skills they turned down for today
(UW3), "something quick", and the converse tool for a chat turn.
"""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from backend.contracts.common import Contract
from backend.contracts.llm import LlmSelection
from backend.contracts.session import Intent, IntentKind
from backend.llm.factory import LlmFactory, NoModelAvailable
from backend.registry.models import Registry

# Words people use for a skill, mapped to the dimension Lodestar trains for it. Order matters:
# "short-term memory" must win over "memory".
SKILL_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bshort[- ]term memory\b", re.I), "short_term_memory"),
    (re.compile(r"\bmemory\b|\bremember(ing)?\b", re.I), "working_memory"),
    (re.compile(r"\b(speed|faster|fast|reaction|quicker)\b", re.I), "processing_speed"),
    (re.compile(r"\b(focus|attention|concentrat\w*)\b", re.I), "selective_attention"),
    (re.compile(r"\b(self[- ]control|impulse\w*|holding back)\b", re.I), "inhibition"),
    (re.compile(r"\b(logic|reasoning|puzzles?)\b", re.I), "reasoning"),
    (re.compile(r"\b(maths?|numbers?|arithmetic)\b", re.I), "numerical_thinking"),
    (re.compile(r"\b(spatial( thinking)?|shapes?|rotat\w*)\b", re.I), "spatial_thinking"),
    (re.compile(r"\b(flexib\w*|switching|multitask\w*)\b", re.I), "cognitive_flexibility"),
]

_DECLINE = re.compile(
    r"\b(not|no|skip|without|anything but|other than|instead of|rather not|don'?t want|"
    r"sick of|tired of|bored of|fed up with|enough)\b(?P<rest>.{0,40})",
    re.I,
)
_QUICK = re.compile(
    r"\b(quick|short|fast one|only (have|got) \d+ min\w*|\d+ min\w*|in a hurry|no time)\b", re.I
)
_ELSE = re.compile(
    r"\b(something else|another (one|game)|different (one|game)|not that one)\b", re.I
)
_THEME = re.compile(r"\babout ([a-z][a-z ]{2,30})$", re.I)
# "Make me a game where I remember a phone number while doing maths" (docs/plan/08).
_CUSTOM = re.compile(
    r"\b((make|invent|create|build|design|dream up) (me |us )?(a |an |my own |a new )?"
    r"(\w+ )?game|(my own|custom|new kind of) game|a game (where|in which|that))\b",
    re.I,
)
CUSTOM_GAME = "custom_blocks"

ToolChoice = Literal[
    "explain",
    "read_profile",
    "get_history",
    "search_memory",
    "session_history",
    "forecast_range",
    "contest",
]

# The user disagrees with a reading of them, or says something outside the game got in the way.
_CONTEST = re.compile(
    r"\b(i disagree|you'?re wrong|you are wrong|that'?s (wrong|not right|not fair|unfair|"
    r"not accurate|inaccurate)|that is (wrong|not right|not fair|unfair|not accurate|inaccurate)|"
    r"(wasn'?t|isn'?t) (a )?fair|(doesn'?t|does not|didn'?t) (reflect|seem right)|"
    r"not (really )?my (real|true|usual|actual)|i was (distracted|interrupted)|"
    r"(got|kept getting|keep getting) (distracted|interrupted)|"
    r"(room|place|it) was (so |too |really )?(noisy|loud)|too (noisy|loud)|"
    r"because of (the )?(noise|distractions?|interruptions?)|(lots|lot) of (noise|distractions?)|"
    r"someone (came in|called|interrupted)|my phone (rang|kept)|phone was ringing)\b",
    re.I,
)

# Patterns per kind. A turn whose patterns point to one kind is routed without asking a model.
_KINDS: list[tuple[IntentKind, re.Pattern[str]]] = [
    (
        "settings",
        re.compile(
            r"\b(settings?|willow|spark|sage|buddy|(change|switch) (my |the )?coach|"
            r"(calmer|friendlier|stricter|funnier|nicer) coach|coach (to|that)|be more (of )?a|"
            r"(push|chill|balanced) mode|mode please|from now on|stop suggesting|"
            r"don'?t suggest|camera|microphone|voice (on|off)|turn (the )?\w+ (on|off))\b",
            re.I,
        ),
    ),
    (
        "experiment",
        re.compile(
            r"\b(experiment|test (if|whether)|real test|compare (morning|evening|my)|"
            r"see (if|whether) \w+ (helps?|is better))\b",
            re.I,
        ),
    ),
    (
        "twin_chat",
        re.compile(
            r"\b(twin|when am i|best time|time of day|am i (better|sharper|faster) in|"
            r"morning or (the )?evening|do i do better)\b",
            re.I,
        ),
    ),
    (
        "goal",
        re.compile(
            r"\b(goal|aim for|target|(want|like|need) (my|to) \w+ .{0,30}\b(solid|better|"
            r"stronger|improve\w*|faster)|improve my|get (better|faster) at|make my \w+ "
            r"(stronger|better|solid)|help me get (better|faster)|my goal|a goal)\b",
            re.I,
        ),
    ),
    (
        "life_context",
        re.compile(
            r"\b(slept|sleep|didn'?t sleep|tired|exhausted|up all night|ill|unwell|sick|"
            r"headache|cold|flu|exams?|exam week|stressed|stress|busy (week|day)|"
            r"jet ?lag|travell?ing|flew)\b",
            re.I,
        ),
    ),
]
_CHAT_TOOLS: list[tuple[ToolChoice, re.Pattern[str]]] = [
    (
        "explain",
        re.compile(
            r"\b(why|how did you (choose|pick|decide)|what made you|explain (your|that|this|the) "
            r"(choice|pick|decision))\b",
            re.I,
        ),
    ),
    (
        "forecast_range",
        re.compile(
            r"\b(will|going to|gonna)\b.{0,40}\b(my|i)\b.{0,40}\b(score|be|reach|get)\b.{0,40}"
            r"\b(next|in a|in one|in \d+|by|later|future)\b|\b(predict|forecast)\b|\bmy future\b|"
            r"\b(exactly|precisely)\b.{0,30}\b(will|score)\b",
            re.I,
        ),
    ),
    (
        "session_history",
        re.compile(
            r"\b(what did i (play|do)|what (have i|games? did i) play\w*|which games? (did|have) i|"
            r"how did i do|my last (session|round|game)|last session|session history|"
            r"play(ed)? (yesterday|last|this|on)|games? (yesterday|last week|this week)|"
            r"show me my history)\b",
            re.I,
        ),
    ),
    (
        "search_memory",
        re.compile(
            r"\b(remember about me|know about me|did i (tell|say|mention)|what did i (say|tell)|"
            r"recall)\b",
            re.I,
        ),
    ),
    (
        "get_history",
        re.compile(
            r"\b(history|over (the )?(last|past)|changed|progress|improv\w*|got better|"
            r"since i started|(last|past|this) (week|month|\d+ days)|trend)\b",
            re.I,
        ),
    ),
    (
        "read_profile",
        re.compile(
            r"\b(how am i doing|my (profile|results?|scores?|strengths?|skills?)|"
            r"(memory|focus|speed|maths?|reasoning) score|how good is my|where am i at|"
            r"show me my)\b",
            re.I,
        ),
    ),
]
_PLAY = re.compile(
    r"\b(play|game|round|start|train|practi[cs]e|let'?s (go|do)|go|again|another|one more|"
    r"ready|warm (me )?up|challenge me|give me|try|do some|can we do|something (quick|for))\b",
    re.I,
)
_SMALL_TALK = re.compile(
    r"^\s*(hi|hello|hey|thanks?( you)?|thank u|ok(ay)?( cool)?|cool|nice|bye|good night|"
    r"who are you|what can you do|how do (the|these) games work)\b",
    re.I,
)


@dataclass(frozen=True)
class Routed:
    intent: Intent
    sure: bool  # the rules alone decided; no model needed


def skills_in(text: str, registry: Registry | None = None) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    if registry is not None:
        for d in registry.dimensions:
            if d.name.lower() in lowered and d.id not in found:
                found.append(d.id)
    for pattern, dim in SKILL_WORDS:
        if pattern.search(text) and dim not in found:
            if dim == "working_memory" and "short_term_memory" in found:
                continue
            found.append(dim)
    return found


def game_in(text: str, registry: Registry) -> str | None:
    lowered = text.lower().replace("\u2019", "'")
    for game in registry.games:  # a story ("the Detective story") is played chapter by chapter
        if (game.available or game.kind == "story") and game.name.lower() in lowered:
            return game.id
    return None


def declined(text: str, registry: Registry | None = None) -> list[str]:
    """Skills the user turned down: 'not memory today', 'skip the maths'."""
    out: list[str] = []
    for match in _DECLINE.finditer(text):
        for dim in skills_in(match.group("rest"), registry):
            if dim not in out:
                out.append(dim)
    return out


def _kinds(text: str) -> list[IntentKind]:
    return [kind for kind, pattern in _KINDS if pattern.search(text)]


def chat_tool(text: str) -> ToolChoice | None:
    for tool, pattern in _CHAT_TOOLS:
        if pattern.search(text):
            return tool
    return None


def classify(text: str, trigger: str, registry: Registry | None = None) -> Routed:
    """Keyword rules. `sure` is False when nothing matched or two kinds compete."""
    stripped = text.strip()
    if not stripped:
        kind: IntentKind = "proactive" if trigger in ("schedule", "proactive") else "play"
        return Routed(Intent(kind=kind), sure=True)
    game = game_in(stripped, registry) if registry is not None else None
    avoid = declined(stripped, registry)
    kinds = _kinds(stripped)
    without_game = stripped
    if game is not None and registry is not None:
        name = re.escape(registry.game(game).name)
        without_game = re.sub(name, "", stripped.replace("\u2019", "'"), flags=re.I)
    quick = bool(_QUICK.search(without_game))  # "Quick Draw" is a name, not a request

    if "settings" in kinds:
        # "stop suggesting memory this week" pauses a skill; it isn't a request to play.
        pause = re.search(r"\b(stop suggesting|don'?t suggest)\b(?P<rest>.{0,40})", stripped, re.I)
        dims = skills_in(pause.group("rest"), registry) if pause else []
        return Routed(Intent(kind="settings", text=stripped, avoid_dims=dims), sure=True)
    tool = chat_tool(stripped)
    if tool == "explain" and not _CONTEST.search(stripped):
        return Routed(Intent(kind="chat", text=stripped, tool=tool), sure=True)
    if _CONTEST.search(stripped):
        return Routed(Intent(kind="chat", text=stripped, tool="contest"), sure=True)
    if _CUSTOM.search(stripped) and game in (None, CUSTOM_GAME):
        # A game made to order: the request text becomes the recipe brief.
        return Routed(Intent(kind="play", text=stripped, game_id=CUSTOM_GAME), sure=True)
    other = bool(_ELSE.search(stripped))
    if avoid or other:
        # Turning a skill down is still a request to play something (UW3).
        intent = Intent(
            kind="play", text=stripped, avoid_dims=avoid, quick=quick, replace_current=other
        )
        return Routed(intent, sure=True)
    for kind in ("experiment", "twin_chat", "goal"):
        if kind in kinds:
            dims = skills_in(stripped, registry)
            return Routed(
                Intent(kind=kind, text=stripped, dim=dims[0] if dims else None),
                sure=True,
            )
    if tool is not None:
        dims = skills_in(stripped, registry)
        intent = Intent(kind="chat", text=stripped, tool=tool, dim=dims[0] if dims else None)
        return Routed(intent, sure=True)
    if "life_context" in kinds:
        return Routed(Intent(kind="life_context", text=stripped), sure=True)
    if game is not None or _PLAY.search(stripped) or quick:
        dims = skills_in(stripped, registry) if game is None else []
        theme = _THEME.search(stripped.rstrip(".!?"))
        return Routed(
            Intent(
                kind="play",
                text=stripped,
                game_id=game,
                dim=dims[0] if dims else None,
                quick=quick,
                theme=theme.group(1).strip().lower() if theme else None,
            ),
            sure=True,
        )
    if _SMALL_TALK.search(stripped):
        return Routed(Intent(kind="chat", text=stripped), sure=True)
    return Routed(Intent(kind="chat", text=stripped), sure=False)


# The structured call used when the rules aren't sure ------------------------------------------

RouterKind = Literal["play", "chat", "twin_chat", "experiment", "goal", "life_context", "settings"]


class RouterOutput(Contract):
    kind: RouterKind
    tool: ToolChoice | None = Field(
        default=None, description="For chat: the tool that answers it, or null for small talk"
    )
    game: str | None = Field(default=None, description="A game the user named, by its name")
    skill: str | None = Field(default=None, description="A skill the user named, in their words")
    avoid_skill: str | None = Field(default=None, description="A skill the user turned down")
    quick: bool = False


ROUTER_PROMPT = """You route messages for Lodestar, a practice coach with short brain games.
Pick the kind:
- play: wants to play now, names a game or skill, or turns one down ("not memory today")
- chat: anything else said to Lodestar. tool = explain (asks why Lodestar chose something),
  read_profile (asks about their skills now), get_history (asks how a skill changed over time),
  search_memory (asks what Lodestar remembers about them), session_history (asks which games they
  played or how a past session went), forecast_range (asks what a skill or score will be in the
  future), contest (disagrees with a result, or says a distraction spoiled it), or null.
- twin_chat: asks their Twin about their own patterns (best time of day, what helps them)
- experiment: wants to test something about themselves over several sessions
- goal: wants to reach a level in a skill by a date
- life_context: tells how their life is going (sleep, exams, stress, feeling unwell)
- settings: wants to change the coach, difficulty mode, camera or microphone
Reply with one JSON object and nothing else, shaped like:
{"kind": "play", "tool": null, "game": null, "skill": null, "avoid_skill": null, "quick": false}
(tool: one of the tools above or null; game, skill and
avoid_skill: the user's words or null; quick: true if they want something short)"""


def from_router(out: RouterOutput, text: str, registry: Registry) -> Intent:
    game = game_in(out.game, registry) if out.game else None
    dims = skills_in(out.skill or "", registry)
    avoid = skills_in(out.avoid_skill or "", registry)
    kind: IntentKind = "play" if avoid and out.kind == "chat" else out.kind
    return Intent(
        kind=kind,
        text=text,
        game_id=game if kind == "play" else None,
        dim=dims[0] if dims else None,
        avoid_dims=avoid,
        quick=out.quick,
        tool=out.tool if kind == "chat" else None,
        source="llm",
    )


async def route(
    text: str,
    trigger: str,
    registry: Registry,
    llm: LlmFactory,
    user_id: UUID,
    selection: LlmSelection,
) -> tuple[Intent, list[str]]:
    """Rules first; when they aren't sure, one structured model call. Without a model, the rules'
    best guess stands. Returns the intent and any fallback taken."""
    routed = classify(text, trigger, registry)
    if routed.sure:
        return routed.intent, []
    messages = [SystemMessage(ROUTER_PROMPT), HumanMessage(text)]
    try:
        out = await llm.structured(user_id, selection, messages, RouterOutput)
    except NoModelAvailable as exc:
        return routed.intent, [*exc.degraded, "router:llm->rules"]
    return from_router(out.value, text, registry), list(out.degraded)
