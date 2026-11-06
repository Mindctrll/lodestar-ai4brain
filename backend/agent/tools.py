"""Converse tools (docs/plan/03, converse subgraph). Typed, validated, and the same functions the
CLI's MCP server will expose (WP3).

Read tools turn data into facts; the coach answers only from those facts (AGENTS.md rule 4).
Write tools first `propose` a question with the facts behind any number in it; they `run` only
after the user confirms, inside one transaction that also writes the event (docs/plan/04).
"""

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range

from backend.acs.score import score as acs_score
from backend.agent import experiments, why
from backend.agent.context import LodestarContext
from backend.agent.intents import game_in
from backend.agent.slots import LifeEvent, named_day
from backend.agent.state import LodestarState
from backend.agent.telemetry import emit
from backend.contracts.common import Contract, DimensionId, GameId, Persona, SuccessMode
from backend.contracts.events import (
    ContextAdded,
    GoalPayload,
    GoalSet,
    SettingsChanged,
    SettingsChangedPayload,
)
from backend.contracts.facts import Fact, FactsPacket, MemoryItem
from backend.contracts.session import Intent, ToolCall, ToolName, ToolOutcome
from backend.contracts.views import DimensionView
from backend.db import tables as t
from backend.db.twin_store import acs_counts, append_event, contest_round, read_twin
from backend.ml.serve import forecast_bands, user_history
from backend.scoring.goals import range_floor, rounds_to_target, suggest_target
from backend.scoring.kalman_elo import Belief
from backend.scoring.levels import TARGET_P

# Arguments ------------------------------------------------------------------------------------


class ReadProfileArgs(Contract):
    dim: DimensionId | None = None
    question: str = ""


class GetHistoryArgs(Contract):
    dim: DimensionId | None = None
    days: int = Field(default=30, ge=1, le=3650)
    question: str = ""


class SearchMemoryArgs(Contract):
    query: str = Field(min_length=1, max_length=300)


class StartGameArgs(Contract):
    game_id: GameId | None = None
    dim: DimensionId | None = None


class ExplainArgs(Contract):
    decision_id: UUID | None = None
    question: str = ""


class SessionHistoryArgs(Contract):
    days: int = Field(default=7, ge=1, le=3650)
    question: str = ""


class ForecastRangeArgs(Contract):
    dim: DimensionId | None = None
    question: str = ""


class ContestArgs(Contract):
    said: str = Field(min_length=1, max_length=2000)


class SetGoalArgs(Contract):
    dim: DimensionId
    target: int = Field(ge=1, le=50, description="Range within ± this many percentage points")
    due: date
    rounds: int | None = Field(default=None, description="About how many rounds that takes")


class LogLifeContextArgs(Contract):
    label: str = Field(min_length=1, max_length=80)
    start: datetime
    end: datetime
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    light: bool = False


class UpdateSettingsArgs(Contract):
    persona: Persona | None = None
    success_mode: SuccessMode | None = None
    pause_dim: DimensionId | None = None
    pause_days: int = Field(default=7, ge=1, le=30)


class StartExperimentArgs(Contract):
    hypothesis: str = Field(min_length=1, max_length=200)
    design: dict[str, Any]


Run = Callable[
    [LodestarContext, LodestarState, ToolCall], Awaitable[tuple[ToolOutcome, dict[str, Any]]]
]


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    args: type[Contract]
    writes: bool
    run: Run
    does: str


# Shared helpers -------------------------------------------------------------------------------


def dim_name(ctx: LodestarContext, dim: str) -> str:
    return ctx.services.registry.dimension(dim).name


def estimate_text(ctx: LodestarContext, view: DimensionView) -> str:
    """The same wording the after-game coach uses, so facts read the same everywhere."""
    name = dim_name(ctx, view.dim)
    text = (
        f"{name} estimate {round(view.percent)}% "
        f"(80% range {round(view.percent_low)}-{round(view.percent_high)}%)"
    )
    return text + (", still learning about you" if view.still_learning else "")


def _numbered(texts: list[tuple[str, str | None]]) -> list[Fact]:
    return [Fact(id=f"F{i + 1}", text=text, dim=dim) for i, (text, dim) in enumerate(texts)]


def _when(d: date) -> str:
    return f"{d.day} {d:%b}"


# Read tools -----------------------------------------------------------------------------------


async def read_profile(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    args = ReadProfileArgs.model_validate(call.args)
    async with ctx.services.engine.connect() as conn:
        twin = await read_twin(conn, ctx.user_id, norms=ctx.services.norms)
    views = [v for v in twin.dims if v.n > 0]
    if args.dim is not None:
        views = [v for v in views if v.dim == args.dim]
        if not views:
            name = dim_name(ctx, args.dim).lower()
            reply = f"I haven't measured your {name} yet. Want to play a {name} game now?"
            return ToolOutcome(name="read_profile", reply=reply), {}
    if not views:
        reply = "I haven't measured any skills yet. Play a round and I'll start learning."
        return ToolOutcome(name="read_profile", reply=reply), {}
    views.sort(key=lambda v: v.percent, reverse=True)
    facts = _numbered([(estimate_text(ctx, v), v.dim) for v in views[:5]])
    instruction = (
        f'The user asked: "{args.question}". Answer in at most 3 sentences from these facts, '
        "with each range."
    )
    return ToolOutcome(
        name="read_profile", facts=FactsPacket(facts=facts), instruction=instruction
    ), {}


async def get_history(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    args = GetHistoryArgs.model_validate(call.args)
    since = datetime.now(UTC).date() - timedelta(days=args.days)
    async with ctx.services.engine.connect() as conn:
        twin = await read_twin(conn, ctx.user_id, norms=ctx.services.norms)
    rows = [h for h in twin.history if h.day >= since and (args.dim is None or h.dim == args.dim)]
    by_dim: dict[str, list[Any]] = {}
    for row in sorted(rows, key=lambda h: h.day):
        by_dim.setdefault(row.dim, []).append(row)
    texts: list[tuple[str, str | None]] = []
    norms = ctx.services.norms
    for dim, points in by_dim.items():
        if len(points) < 2:
            continue
        first, last = points[0], points[-1]
        a = norms.percentile(dim, Belief(first.mu, first.sigma))
        b = norms.percentile(dim, Belief(last.mu, last.sigma))
        texts.append(
            (
                f"{dim_name(ctx, dim)} was {round(a.value)}% (80% range {round(a.low)}-"
                f"{round(a.high)}%) on {_when(first.day)} and {round(b.value)}% (80% range "
                f"{round(b.low)}-{round(b.high)}%) on {_when(last.day)}",
                dim,
            )
        )
    if not texts:
        what = dim_name(ctx, args.dim).lower() if args.dim else "any skill"
        reply = (
            f"I don't have enough days of {what} in that time to show a change yet. "
            "A few more sessions and I will."
        )
        return ToolOutcome(name="get_history", reply=reply), {}
    instruction = (
        f'The user asked: "{args.question}". Answer in at most 3 sentences from these facts. '
        "Compare the two days with their ranges; if the ranges overlap, say the change isn't "
        "clear yet."
    )
    outcome = ToolOutcome(
        name="get_history", facts=FactsPacket(facts=_numbered(texts[:4])), instruction=instruction
    )
    return outcome, {}


async def search_memory(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    args = SearchMemoryArgs.model_validate(call.args)
    memory = ctx.services.memory
    if memory is None:
        reply = "I can't look through my notes right now. Try again in a little while."
        return ToolOutcome(name="search_memory", reply=reply), {}
    hits = await memory.recall(ctx.user_id, args.query, limit=4)  # filtered by user (rule 7)
    if not hits:
        reply = "I don't have anything saved about that yet."
        return ToolOutcome(name="search_memory", reply=reply), {}
    items = [MemoryItem(id=f"M{i + 1}", text=h.text) for i, h in enumerate(hits)]
    instruction = (
        f'The user asked: "{args.query}". Say in at most 3 sentences what you remember, '
        "citing each memory. Only what the memories say."
    )
    outcome = ToolOutcome(
        name="search_memory", facts=FactsPacket(memories=items), instruction=instruction
    )
    return outcome, {}


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


async def _user_today(conn: Any, user_id: UUID) -> tuple[str, date]:
    tz = (
        await conn.execute(select(t.users.c.timezone).where(t.users.c.user_id == user_id))
    ).scalar_one_or_none() or "UTC"
    today = (await conn.execute(select(func.date(func.timezone(tz, func.now()))))).scalar_one()
    return tz, today


async def explain(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """UW7, the "why" audit: the latest pick (or the one on the day, or of the game, the user names)
    with its top candidates, their scores and the data behind it."""
    args = ExplainArgs.model_validate(call.args)
    registry = ctx.services.registry
    query = select(t.decisions).where(t.decisions.c.user_id == ctx.user_id)
    day: date | None = None
    if args.decision_id is not None:
        query = query.where(t.decisions.c.decision_id == args.decision_id)
    else:
        query = query.where(t.decisions.c.node == "plan_next")
    async with ctx.services.engine.connect() as conn:
        tz, today = await _user_today(conn, ctx.user_id)
        if args.decision_id is None:
            day = named_day(args.question, today)
            game = game_in(args.question, registry)
            if game is not None:
                dim = registry.game(game).primary_dims[0]
                query = query.where(t.decisions.c.chosen.in_([f"{dim}:{game}", dim]))
        latest = query.order_by(t.decisions.c.ts.desc()).limit(1)
        on_day = (
            latest.where(func.date(func.timezone(tz, t.decisions.c.ts)) == day)
            if day is not None
            else latest
        )
        row = (await conn.execute(on_day)).one_or_none()
        if row is None and day == today:  # "why this game today?" before today's first pick
            row = (await conn.execute(latest)).one_or_none()
    if row is None:
        reply = (
            f"I don't have a pick saved for {why.day_words(day, today).removeprefix('on ')}."
            if day is not None
            else "I haven't picked a game for you yet. Say 'play' and I'll explain my pick."
        )
        return ToolOutcome(name="explain", reply=reply), {}
    facts = [Fact(id="D1", text=row.reason, decision=True, ref=str(row.decision_id))]
    for i, cand in enumerate(row.candidates[:3]):
        option = cand["option"]
        known = any(d.id == option for d in registry.dimensions)
        label = registry.dimension(option).name if known else option
        parts = ", ".join(
            f"{k.replace('_', ' ')} {v:.2f}" for k, v in cand["breakdown"].items() if abs(v) > 1e-9
        )
        text = f"{label} scored {cand['score']:.2f}" + (f" ({parts})" if parts else "")
        facts.append(Fact(id=f"F{i + 1}", text=text, dim=option if label != option else None))
    lines = why.decode(row.evidence or [])
    cited: list[str] = []
    for line in lines:
        fact = Fact(id=f"F{len(facts)}", text=f"{line.source}: {line.text}")
        facts.append(fact)
        cited.append(f"{line.text} [{fact.id}].")
    instruction = (
        f'The user asked: "{args.question}". Explain the pick in at most 3 sentences: first the '
        "reason [D1], then the data behind it, naming the chart it comes from. Cite every fact "
        "you use."
    )
    fallback = f"{row.reason.rstrip('.')} [D1]."
    if cited:
        fallback += " " + " ".join(cited[:2])
    elif len(facts) > 1:
        fallback += f" Top of my list: {facts[1].text} [F1]."
    emit(
        {
            "kind": "card",
            "card": "why",
            "decision_id": str(row.decision_id),
            "reason": row.reason,
            "when": why.day_words(row.ts.astimezone(ZoneInfo(tz)).date(), today),
            "lines": [line.model_dump() for line in lines],
            "chosen": str(row.chosen).split(":")[0],
        }
    )
    outcome = ToolOutcome(
        name="explain",
        facts=FactsPacket(facts=facts),
        instruction=instruction,
        fallback=fallback,
    )
    return outcome, {}


async def session_history(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """What the user played and how it went, day by day, with the pick behind each session."""
    args = SessionHistoryArgs.model_validate(call.args)
    registry = ctx.services.registry
    async with ctx.services.engine.connect() as conn:
        tz, today = await _user_today(conn, ctx.user_id)
        only = named_day(args.question, today)
        since = today - timedelta(days=args.days if "last" in args.question.lower() else 7)
        local = func.date(func.timezone(tz, t.rounds.c.started_at))
        where = [
            t.rounds.c.user_id == ctx.user_id,
            t.rounds.c.status.in_(["completed", "eased"]),
            local == only if only is not None else local >= since,
        ]
        game = game_in(args.question, registry)
        if game is not None:
            where.append(t.rounds.c.game_id == game)
        rows = (
            await conn.execute(
                select(
                    t.rounds.c.game_id,
                    t.rounds.c.score,
                    t.rounds.c.session_id,
                    local.label("day"),
                )
                .where(*where)
                .order_by(t.rounds.c.started_at.desc())
                .limit(40)
            )
        ).all()
        sessions = {r.session_id for r in rows}
        picks: dict[Any, str] = {}
        if sessions:
            for d in await conn.execute(
                select(t.decisions.c.session_id, t.decisions.c.decision_id)
                .where(
                    t.decisions.c.user_id == ctx.user_id,
                    t.decisions.c.node == "plan_next",
                    t.decisions.c.session_id.in_(sessions),
                )
                .order_by(t.decisions.c.ts)
            ):
                picks.setdefault(d.session_id, str(d.decision_id))
    if not rows:
        when = why.day_words(only, today) if only else f"in the last {args.days} days"
        return ToolOutcome(
            name="session_history", reply=f"I don't see any finished rounds {when}."
        ), {}
    by_day: dict[date, list[Any]] = {}
    for r in rows:
        by_day.setdefault(r.day, []).append(r)

    def shown(r: Any) -> str:
        name = registry.game(r.game_id).name
        return (
            f"{name} ({round(r.score * 100)}%)" if r.score is not None else f"{name} (not counted)"
        )

    scores = [float(r.score) for r in rows if r.score is not None]
    facts: list[Fact] = []
    if scores:
        facts.append(
            Fact(
                id="F1",
                text=f"{len(rows)} round{'s' if len(rows) != 1 else ''} on {len(by_day)} "
                f"day{'s' if len(by_day) != 1 else ''}, "
                f"{round(100 * sum(scores) / len(scores))}% right on average",
            )
        )
    for day, group in list(by_day.items())[:4]:
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"{_first_up(why.day_words(day, today))} you played "
                + ", ".join(shown(r) for r in group[:5]),
            )
        )
    emit(
        {
            "kind": "card",
            "card": "history",
            "rows": [
                {
                    "day": why.day_words(r.day, today),
                    "game": registry.game(r.game_id).name,
                    "score": None if r.score is None else round(r.score * 100),
                    "decision_id": picks.get(r.session_id),
                }
                for r in rows[:12]
            ],
        }
    )
    outcome = ToolOutcome(
        name="session_history",
        facts=FactsPacket(facts=facts),
        instruction=(
            f'The user asked: "{args.question}". Answer in at most 3 sentences from these facts. '
            "Say which games they played and how it went."
        ),
        fallback=" ".join(f"{f.text} [{f.id}]." for f in facts[:3]),
    )
    return outcome, {}


FORECAST_SKILLS = 3


async def forecast_range(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """A question about the future gets a range, how often such ranges hold, and no promises
    (AGENTS.md rule 5). There is no overall score to predict: each skill has its own."""
    args = ForecastRangeArgs.model_validate(call.args)
    services = ctx.services
    lowered = args.question.lower()
    span = 7 if "week" in lowered else 30
    async with services.engine.connect() as conn:
        pace = (
            await conn.execute(
                select(func.count())
                .select_from(t.sessions)
                .where(
                    t.sessions.c.user_id == ctx.user_id,
                    t.sessions.c.started_at >= datetime.now(UTC) - timedelta(days=span),
                )
            )
        ).scalar_one()
        twin = await read_twin(conn, ctx.user_id, norms=services.norms)
        metrics = (
            await conn.execute(
                select(t.ml_models.c.metrics).where(
                    t.ml_models.c.name == "growth_forecast", t.ml_models.c.active.is_(True)
                )
            )
        ).scalar_one_or_none()
    sessions = min(max(int(pace), 1), 20)
    bands = (
        forecast_bands(
            services.forecaster,
            services.registry,
            await user_history(services.engine, ctx.user_id),
            sessions,
        )
        if services.forecaster is not None
        else {}
    )
    views = {v.dim: v for v in twin.dims if v.n > 0}
    if args.dim is not None:
        wanted = [args.dim]
    else:
        wanted = sorted(views, key=lambda d: views[d].n, reverse=True)
    chosen = [d for d in wanted if d in bands and d in views][:FORECAST_SKILLS]
    honest = "I can't give you an exact number, and no honest coach could: a forecast is a range."
    if not chosen:
        reply = (
            f"{honest} I don't have enough practice days yet to draw one for you. "
            "Play on a few more days and I will."
        )
        return ToolOutcome(name="forecast_range", reply=reply), {}

    def pct(dim: str, mu: float) -> int:
        return round(services.norms.percentile(dim, Belief(mu, 1e-4)).value)

    facts: list[Fact] = []
    rows: list[dict[str, Any]] = []
    for dim in chosen:
        band, view, name = bands[dim], views[dim], dim_name(ctx, dim)
        low, mid, high = pct(dim, band.low), pct(dim, band.median), pct(dim, band.high)
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"Forecast for {name} after {sessions} more sessions: {mid}% "
                f"(80% range {low}-{high}%)",
                dim=dim,
            )
        )
        rows.append(
            {
                "name": name,
                "now": round(view.percent),
                "now_low": round(view.percent_low),
                "now_high": round(view.percent_high),
                "low": low,
                "median": mid,
                "high": high,
            }
        )
    held: int | None = None
    by_k = (metrics or {}).get("by_k", {})
    nearest = min(by_k, key=lambda k: abs(int(k) - sessions), default=None)
    if nearest is not None:
        held = round(100 * float(by_k[nearest].get("coverage", 0)))
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"On players the model never saw, its 80% ranges held {held}% of the time",
            )
        )
    first, name = rows[0], dim_name(ctx, chosen[0])
    text = (
        f"{honest} At your current pace, after {sessions} more sessions your {name.lower()} is "
        f"likely between {first['low']}% and {first['high']}% [F1]."
    )
    if held is not None:
        text += (
            f" Ranges like this held {held}% of the time on players the model never saw "
            f"[{facts[-1].id}]."
        )
    emit(
        {
            "kind": "card",
            "card": "forecast",
            "sessions": sessions,
            "held": held,
            "rows": rows,
        }
    )
    outcome = ToolOutcome(
        name="forecast_range",
        facts=FactsPacket(facts=facts),
        instruction=(
            f'The user asked: "{args.question}". Do not give one number and make no promises: say '
            "you can't be exact, then give the 80% range from the facts, using the word likely. "
            "At most 3 sentences."
        ),
        fallback=text,
    )
    return outcome, {}


async def contest(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """The user pushes back on a reading (a noisy room, an interruption). Lodestar doesn't defend
    the profile: the estimate stays, its range gets wider, and speaking up counts toward the AI
    Collaboration Score. The user's words are the request, and only the range changes, so this
    doesn't ask for a yes first."""
    args = ContestArgs.model_validate(call.args)
    services = ctx.services
    async with services.engine.connect() as conn:
        before = acs_score(await acs_counts(conn, ctx.user_id))  # type: ignore[arg-type]
    result = await contest_round(
        services.engine, ctx.user_id, ctx.session_id, services.registry, args.said
    )
    if result is None:
        reply = "There's no round to look at yet. Play one and tell me how it felt."
        return ToolOutcome(name="contest", reply=reply), {}
    if not result.counted:
        reply = (
            "Thanks for telling me. That round already didn't count toward your profile, so "
            "nothing needs undoing."
        )
        return ToolOutcome(name="contest", reply=reply), {}
    if not result.new:
        reply = "I've already noted that about this round, and its range is still wider for it."
        return ToolOutcome(name="contest", reply=reply), {}
    async with services.engine.connect() as conn:
        after = acs_score(await acs_counts(conn, ctx.user_id))  # type: ignore[arg-type]

    def pct(dim: str, mu: float, sigma: float) -> tuple[int, int, int]:
        p = services.norms.percentile(dim, Belief(mu, sigma))
        return round(p.value), round(p.low), round(p.high)

    facts: list[Fact] = []
    dims: list[dict[str, Any]] = []
    for change in result.changes:
        name = dim_name(ctx, change.dim)
        _, low, high = pct(change.dim, change.mu_before, change.sigma_before)
        value2, low2, high2 = pct(change.dim, change.mu_after, change.sigma_after)
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"{name} estimate {value2}%: 80% range widened from {low}-{high}% to "
                f"{low2}-{high2}%",
                dim=change.dim,
            )
        )
        dims.append(
            {
                "name": name,
                "value": value2,
                "before_low": low,
                "before_high": high,
                "after_low": low2,
                "after_high": high2,
            }
        )
    parts = ["Fair point: you know what was around you, and I don't."]
    if facts:
        first = dims[0]
        parts.append(
            f"I kept your {first['name'].lower()} estimate at {first['value']}% but widened its "
            f"range from {first['before_low']}-{first['before_high']}% to "
            f"{first['after_low']}-{first['after_high']}% [F1]."
        )
    if after.value is not None and after.low is not None and after.high is not None:
        # One moment moves the score a little: one decimal, so "up from" stays true.
        now_text = f"{after.value:.1f}"
        was = "not enough data" if before.value is None else f"{before.value:.1f}"
        fact = Fact(
            id=f"F{len(facts) + 1}",
            text=f"AI Collaboration Score {now_text} (80% range {round(after.low)}-"
            f"{round(after.high)}), was {was}",
        )
        facts.append(fact)
        parts.append(
            f"Questioning me counts as good collaboration: your AI Collaboration Score is now "
            f"{now_text}, likely {round(after.low)}-{round(after.high)}, up from {was} [{fact.id}]."
        )
    parts.append("A clean round will settle it. Say 'play' when you're ready.")
    emit(
        {
            "kind": "card",
            "card": "pushback",
            "game": services.registry.game(result.game_id).name,
            "dims": dims,
            "acs_before": None if before.value is None else round(before.value, 1),
            "acs_after": None if after.value is None else round(after.value, 1),
            "acs_low": None if after.low is None else round(after.low),
            "acs_high": None if after.high is None else round(after.high),
        }
    )
    return ToolOutcome(name="contest", facts=FactsPacket(facts=facts), reply=" ".join(parts)), {}


async def start_game(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """Hand over to plan_next with what the user asked for; the policy still decides."""
    args = StartGameArgs.model_validate(call.args)
    intent = Intent(kind="play", game_id=args.game_id, dim=args.dim)
    return ToolOutcome(name="start_game"), {"intent": intent}


# Write tools ----------------------------------------------------------------------------------


async def goal_facts(ctx: LodestarContext, args: SetGoalArgs) -> FactsPacket:
    async with ctx.services.engine.connect() as conn:
        twin = await read_twin(conn, ctx.user_id, norms=ctx.services.norms)
    view = next((v for v in twin.dims if v.dim == args.dim), None)
    name = dim_name(ctx, args.dim)
    facts = [
        Fact(
            id="F1",
            text=f"Goal: {name} range within ±{args.target} points by {_when(args.due)}",
            dim=args.dim,
        )
    ]
    if view is not None and view.n > 0:
        now = math.ceil((view.percent_high - view.percent_low) / 2)
        facts.append(
            Fact(
                id="F2",
                text=f"{name} range now ±{now} points (80% range "
                f"{round(view.percent_low)}-{round(view.percent_high)}%)",
                dim=args.dim,
            )
        )
    if args.rounds:
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"About {args.rounds} more {name.lower()} rounds",
                dim=args.dim,
            )
        )
    return FactsPacket(facts=facts)


async def propose_goal(
    ctx: LodestarContext, dim: str, due: date, call_id: UUID, target: int | None = None
) -> ToolCall:
    """Lodestar suggests a reachable target, or uses the one the user named; never one narrower
    than the range can get (the floor plus 2 points, as in `suggest_target`)."""
    async with ctx.services.engine.connect() as conn:
        twin = await read_twin(conn, ctx.user_id, norms=ctx.services.norms)
    view = next((v for v in twin.dims if v.dim == dim), None)
    belief = Belief(view.mu, view.sigma) if view is not None else Belief()
    norms = ctx.services.norms
    floor = math.ceil(range_floor(belief, dim, norms)) + 2
    widened = target is not None and target < floor
    target = max(target, floor) if target else suggest_target(belief, dim, norms)
    rounds = rounds_to_target(belief, dim, target, norms)
    args = SetGoalArgs(dim=dim, target=target, due=due, rounds=rounds or None)
    packet = await goal_facts(ctx, args)
    name = dim_name(ctx, dim).lower()
    goal_id = packet.facts[0].id
    prefix = ""
    if widened:  # say so, rather than quietly set a different goal than the one asked for
        closest = Fact(
            id=f"F{len(packet.facts) + 1}",
            text=f"Closest {name} range Lodestar can reach: ±{target} points",
            dim=dim,
        )
        packet = FactsPacket(facts=[*packet.facts, closest])
        prefix = f"I can't get your {name} range narrower than ±{target} points [{closest.id}]. "
    if rounds:
        rounds_id = next(f.id for f in packet.facts if f.text.startswith("About "))
        prompt = prefix + (
            f"Let's aim for your {name} range to be within ±{target} points by {_when(due)} "
            f"[{goal_id}]. That means about {rounds} more {name} rounds [{rounds_id}]. "
            "Shall I set this goal?"
        )
    else:
        prompt = prefix + (
            f"Let's keep your {name} range within ±{target} points until {_when(due)} "
            f"[{goal_id}]. Regular practice keeps it there. Shall I set this goal?"
        )
    return ToolCall(
        call_id=call_id,
        name="set_goal",
        args=args.model_dump(mode="json"),
        writes=True,
        prompt=prompt,
        facts=packet,
    )


async def set_goal(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    args = SetGoalArgs.model_validate(call.args)
    now = datetime.now(UTC)
    async with ctx.services.engine.begin() as conn:
        exists = (
            await conn.execute(
                select(func.count()).select_from(t.goals).where(t.goals.c.goal_id == call.call_id)
            )
        ).scalar_one()
        if not exists:  # a re-run after a crash must not set the goal twice
            await conn.execute(
                update(t.goals)
                .where(
                    t.goals.c.user_id == ctx.user_id,
                    t.goals.c.dim == args.dim,
                    t.goals.c.status == "active",
                )
                .values(status="dropped")
            )
            await conn.execute(
                t.goals.insert().values(
                    goal_id=call.call_id,
                    user_id=ctx.user_id,
                    dim=args.dim,
                    kind="range",
                    target=args.target,
                    due=args.due,
                )
            )
            await append_event(
                conn,
                GoalSet(
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    ts=now,
                    payload=GoalPayload(
                        goal_id=call.call_id,
                        dim=args.dim,
                        kind="range",
                        target=args.target,
                        due=args.due,
                    ),
                ),
            )
    name = dim_name(ctx, args.dim).lower()
    goal_fact = call.facts.facts[0].id if call.facts.facts else "F1"
    reply = (
        f"Goal set: your {name} range within ±{args.target} points by {_when(args.due)} "
        f"[{goal_fact}]. I'll pick {name} more often until then [{goal_fact}]."
    )
    goal_dims = sorted({*state.goal_dims, args.dim})
    return ToolOutcome(name="set_goal", facts=call.facts, reply=reply), {"goal_dims": goal_dims}


def propose_life_context(event: LifeEvent, tz: Any, call_id: UUID) -> ToolCall:
    args = LogLifeContextArgs(
        label=event.label, start=event.start, end=event.end, light=event.light
    )
    prompt = (
        "Results in that time would count less toward your profile. "
        f'Want me to note "{event.label}" for {period_words(event, tz)}?'
    )
    return ToolCall(
        call_id=call_id,
        name="log_life_context",
        args=args.model_dump(mode="json"),
        writes=True,
        prompt=prompt,
    )


def period_words(event: LifeEvent, tz: Any) -> str:
    start = event.start.astimezone(tz).date()
    last = (event.end - timedelta(seconds=1)).astimezone(tz).date()
    if last == start:
        return "today"
    if last == start + timedelta(days=1):
        return "today and tomorrow"
    return f"today until {last:%A} {_when(last)}"


async def log_life_context(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """UW9: a labelled window in which rounds count less (scoring weight 0.5)."""
    args = LogLifeContextArgs.model_validate(call.args)
    window = LifeEvent(args.label, args.start, args.end, args.light).window(
        call.call_id, args.weight
    )
    async with ctx.services.engine.begin() as conn:
        exists = (
            await conn.execute(
                select(func.count())
                .select_from(t.life_context)
                .where(t.life_context.c.context_id == call.call_id)
            )
        ).scalar_one()
        if not exists:
            await conn.execute(
                t.life_context.insert().values(
                    context_id=call.call_id,
                    user_id=ctx.user_id,
                    label=args.label,
                    period=Range(args.start, args.end, bounds="[)"),
                    weight=args.weight,
                )
            )
            await append_event(
                conn,
                ContextAdded(
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    ts=datetime.now(UTC),
                    payload=window,
                ),
            )
    days = (args.end - args.start).total_seconds() / 86_400
    if days <= 1.01:
        light = " I'll keep today light, and" if args.light else ""
        reply = (
            f"Thanks for telling me.{light} today's results will count less toward your profile."
        )
        reply = reply.replace(". today's", ". Today's")
    else:
        reply = "Thanks for telling me. Until then, results will count less toward your profile."
    update_: dict[str, Any] = {"context": [*state.context, window]}
    if args.light and days <= 1.01:
        update_["success_mode"] = "chill"
    return ToolOutcome(name="log_life_context", reply=reply), update_


def propose_settings(ctx: LodestarContext, args: UpdateSettingsArgs, call_id: UUID) -> ToolCall:
    asks: list[str] = []
    facts: list[Fact] = []
    if args.persona is not None:
        asks.append(f"switch your coach to {args.persona.capitalize()}")
    if args.success_mode is not None:
        target = round(TARGET_P[args.success_mode] * 100)
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"{args.success_mode.capitalize()} mode aims for about {target}% success",
            )
        )
        asks.append(
            f"switch to {args.success_mode.capitalize()} mode, so games aim for about "
            f"{target}% success [{facts[-1].id}]"
        )
    if args.pause_dim is not None:
        name = dim_name(ctx, args.pause_dim).lower()
        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                text=f"Pause {name} suggestions for {args.pause_days} days",
                dim=args.pause_dim,
            )
        )
        asks.append(
            f"stop suggesting {name} for {args.pause_days} days [{facts[-1].id}] "
            "(you can still ask for it)"
        )
    prompt = "Shall I " + " and ".join(asks) + "?"
    return ToolCall(
        call_id=call_id,
        name="update_settings",
        args=args.model_dump(mode="json"),
        writes=True,
        prompt=prompt,
        facts=FactsPacket(facts=facts),
    )


async def update_settings(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    """UW20 (coach and difficulty mode) and UW3 (stop suggesting a skill for a while)."""
    args = UpdateSettingsArgs.model_validate(call.args)
    now = datetime.now(UTC)
    until = now + timedelta(days=args.pause_days) if args.pause_dim else None
    async with ctx.services.engine.begin() as conn:
        values: dict[str, Any] = {}
        if args.persona is not None:
            values["persona"] = args.persona
        if args.success_mode is not None:
            values["success_mode"] = args.success_mode
        if values:
            await conn.execute(
                update(t.users).where(t.users.c.user_id == ctx.user_id).values(**values)
            )
        if args.pause_dim is not None and until is not None:
            done = (
                await conn.execute(
                    select(func.count())
                    .select_from(t.skill_pauses)
                    .where(t.skill_pauses.c.pause_id == call.call_id)
                )
            ).scalar_one()
            if not done:
                await conn.execute(
                    t.skill_pauses.insert().values(
                        pause_id=call.call_id, user_id=ctx.user_id, dim=args.pause_dim, until=until
                    )
                )
        await append_event(
            conn,
            SettingsChanged(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                ts=now,
                payload=SettingsChangedPayload(
                    persona=args.persona,
                    success_mode=args.success_mode,
                    paused_dim=args.pause_dim,
                    paused_until=until,
                ),
            ),
        )
    said: list[str] = []
    state_update: dict[str, Any] = {}
    if args.persona is not None:
        said.append(f"Your coach is now {args.persona.capitalize()}.")
        state_update["persona"] = args.persona
    if args.success_mode is not None:
        mode_fact = next(f.id for f in call.facts.facts if "mode aims" in f.text)
        target = round(TARGET_P[args.success_mode] * 100)
        said.append(f"Games now aim for about {target}% success [{mode_fact}].")
        state_update["success_mode"] = args.success_mode
    if args.pause_dim is not None and until is not None:
        name = dim_name(ctx, args.pause_dim).lower()
        pause_fact = next(f.id for f in call.facts.facts if f.text.startswith("Pause "))
        said.append(
            f"I won't suggest {name} for {args.pause_days} days [{pause_fact}]. "
            "You can still ask for it."
        )
    reply = "Done. " + " ".join(said)
    return ToolOutcome(name="update_settings", facts=call.facts, reply=reply), state_update


DEFAULT_EXPERIMENT_GAMES = ["quick_draw", "arrow_storm", "echo"]


async def propose_experiment(ctx: LodestarContext, call_id: UUID) -> ToolCall:
    """UW10: three sessions in the morning and three in the evening, with the same three games
    (the ones this person plays most, so the comparison is fair)."""
    registry = ctx.services.registry
    async with ctx.services.engine.connect() as conn:
        rows = await conn.execute(
            select(t.rounds.c.game_id, func.count().label("n"))
            .where(t.rounds.c.user_id == ctx.user_id, t.rounds.c.status == "completed")
            .group_by(t.rounds.c.game_id)
            .order_by(func.count().desc())
        )
        played = [
            r.game_id
            for r in rows
            if registry.game(r.game_id).available
            and registry.game(r.game_id).consent is None
            and registry.game(r.game_id).origin
            != "custom"  # a new recipe each time: not comparable
        ]
    games = (played + [g for g in DEFAULT_EXPERIMENT_GAMES if g not in played])[:3]
    plan = experiments.design(games, None)
    names = ", ".join(registry.game(g).name for g in games)
    per = plan["sessions_per_condition"]
    fact = Fact(
        id="F1",
        text=f"{per * 2} sessions: {per} in the morning (5:00-12:00) and {per} in the evening "
        f"(18:00-24:00), each with {names}",
    )
    prompt = (
        f"Want to test whether you do better in the morning or the evening? {per * 2} sessions, "
        f"{per} in each, with the same games [F1]. When you play in one of those times, I'll "
        "count it. Shall I start?"
    )
    args = StartExperimentArgs(hypothesis="Morning or evening: which goes better?", design=plan)
    return ToolCall(
        call_id=call_id,
        name="start_experiment",
        args=args.model_dump(mode="json"),
        writes=True,
        prompt=prompt,
        facts=FactsPacket(facts=[fact]),
    )


async def experiment_in_progress(ctx: LodestarContext) -> ToolOutcome | None:
    """One experiment at a time: if one is running, say how far along it is."""
    async with ctx.services.engine.connect() as conn:
        current = await experiments.running(conn, ctx.user_id)
    if current is None:
        return None
    done = experiments.progress(current)
    fact = Fact(
        id="F1",
        text="Experiment so far: "
        + ", ".join(f"{n} {c} sessions" for c, n in done.items())
        + f" of {current.design['sessions_per_condition']} each",
    )
    return ToolOutcome(
        facts=FactsPacket(facts=[fact]),
        reply="An experiment is already running [F1]. Play in the morning or the evening "
        "to add to it.",
    )


async def start_experiment(
    ctx: LodestarContext, state: LodestarState, call: ToolCall
) -> tuple[ToolOutcome, dict[str, Any]]:
    args = StartExperimentArgs.model_validate(call.args)
    async with ctx.services.engine.begin() as conn:
        await experiments.start(
            conn, ctx.user_id, ctx.session_id, call.call_id, args.hypothesis, args.design
        )
    reply = (
        "Experiment started [F1]. Play in the morning or the evening and I'll use these games; "
        "you'll see the progress on the Experiments page."
    )
    return ToolOutcome(name="start_experiment", facts=call.facts, reply=reply), {}


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec("read_profile", ReadProfileArgs, False, read_profile, "Current skill estimates"),
        ToolSpec("get_history", GetHistoryArgs, False, get_history, "How a skill changed"),
        ToolSpec(
            "search_memory", SearchMemoryArgs, False, search_memory, "What Lodestar remembers"
        ),
        ToolSpec("start_game", StartGameArgs, False, start_game, "Start a round"),
        ToolSpec("explain", ExplainArgs, False, explain, "Why Lodestar chose something"),
        ToolSpec(
            "session_history", SessionHistoryArgs, False, session_history, "Past rounds, by day"
        ),
        ToolSpec(
            "forecast_range",
            ForecastRangeArgs,
            False,
            forecast_range,
            "A skill's future, as a range",
        ),
        # Writes, but needs no yes: the user's own words are the request (see `contest`).
        ToolSpec("contest", ContestArgs, False, contest, "Disagree with a round's reading"),
        ToolSpec("set_goal", SetGoalArgs, True, set_goal, "Set a range goal for a skill"),
        ToolSpec(
            "log_life_context", LogLifeContextArgs, True, log_life_context, "Note sleep, exams…"
        ),
        ToolSpec(
            "update_settings", UpdateSettingsArgs, True, update_settings, "Coach, mode, pauses"
        ),
        ToolSpec(
            "start_experiment",
            StartExperimentArgs,
            True,
            start_experiment,
            "Test morning against evening",
        ),
    )
}
