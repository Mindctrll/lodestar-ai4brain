"""The play loop: plan_next -> prepare_exercise -> play (pause) -> score_update -> monitor
(docs/plan/03). Code decides; nothing here asks an LLM what to do."""

import contextlib
import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import any_, func, literal, select

from backend.agent.affect import estimate
from backend.agent.context import NajmaContext
from backend.agent.nodes.perceive import read_twin_snapshot
from backend.agent.state import NajmaState
from backend.agent.telemetry import emit, record_decision, traced
from backend.contracts.affect import AffectReading
from backend.contracts.decision import Candidate, Decision
from backend.contracts.events import AffectEstimated
from backend.contracts.exercise import ExerciseSpec, RoundResult
from backend.contracts.session import RoundSummary, SessionPlan, Verdict
from backend.db import tables as t
from backend.db.twin_store import append_event, score_round_tx, start_round
from backend.registry.models import Game, Registry
from backend.scoring.kalman_elo import SIGMA_START, Belief
from backend.scoring.levels import TARGET_P, b_for_level, choose_mode, knobs_for, next_level

# docs/plan/03, "How plan_next decides". bandit_gain, goal_weight and plan_priority arrive with
# WP2.3 and WP3.3; they are 0 until then and still shown in the breakdown.
WEIGHTS = {
    "uncertainty": 0.35,
    "staleness": 0.20,
    "goal_weight": 0.20,
    "plan_priority": 0.15,
    "bandit_gain": 0.10,
    "fatigue_penalty": -0.25,
    "repetition": -0.15,
}
STALENESS_CAP_DAYS = 21.0


def core_games_by_dim(registry: Registry) -> dict[str, list[Game]]:
    """Core games the browser can run, by primary skill."""
    out: dict[str, list[Game]] = {}
    for game in registry.games:
        if game.phase == "P1" and game.kind == "game" and game.available:
            for dim in game.primary_dims:
                out.setdefault(dim, []).append(game)
    return out


def _belief(state: NajmaState, dim: str) -> Belief:
    if state.twin and dim in state.twin.dims:
        d = state.twin.dims[dim]
        return Belief(d.mu, d.sigma, d.n, d.last_practised)
    return Belief()


def _days_since(belief: Belief, now: datetime) -> float | None:
    if belief.last_practised is None:
        return None
    return (now - belief.last_practised).total_seconds() / 86_400


CHECKUP_AFTER_DAYS = 14.0  # UW15: after a long break, measure before training
CHECKUP_ROUNDS = 3


def _pick(options: list[Game], last_game: str | None, seed: int) -> Game:
    choices = [g for g in options if g.id != last_game] or options
    return random.Random(seed).choice(choices)


QUICK_S = 60  # "something quick": games of a minute or less
NUDGE_AFTER = 3  # UW3: sessions in a row a skill was turned down before Najma asks once


def _length(game: Game) -> str:
    s = game.duration_s
    return f"{s // 60}-minute" if s % 60 == 0 else f"{s}-second"


async def _abandon(ctx: NajmaContext, round_id: Any) -> None:
    """A new pick replaces a game that was waiting ("not memory today"): it's never scored."""
    async with ctx.services.engine.begin() as conn:
        await conn.execute(
            t.rounds.update()
            .where(
                t.rounds.c.round_id == round_id,
                t.rounds.c.user_id == ctx.user_id,
                t.rounds.c.status == "started",
            )
            .values(status="abandoned", ended_at=datetime.now(UTC))
        )


async def paused_dims(ctx: NajmaContext, now: datetime) -> set[str]:
    """Skills the user asked Najma to stop suggesting for a while (UW3)."""
    async with ctx.services.engine.connect() as conn:
        rows = await conn.execute(
            select(t.skill_pauses.c.dim).where(
                t.skill_pauses.c.user_id == ctx.user_id, t.skill_pauses.c.until > now
            )
        )
        return {r.dim for r in rows}


async def should_nudge(ctx: NajmaContext, dim: str) -> bool:
    """True once a skill was turned down in NUDGE_AFTER sessions in a row, unless Najma already
    asked about it in that run of sessions."""
    async with ctx.services.engine.connect() as conn:
        sessions = [
            r.session_id
            for r in await conn.execute(
                select(t.sessions.c.session_id)
                .where(t.sessions.c.user_id == ctx.user_id)
                .order_by(t.sessions.c.started_at.desc())
                .limit(10)
            )
        ]
        rows = await conn.execute(
            select(t.decisions.c.session_id, t.decisions.c.node).where(
                t.decisions.c.user_id == ctx.user_id,
                t.decisions.c.session_id.in_(sessions),
                (
                    (t.decisions.c.node == "plan_next")
                    & (literal(f"declined:{dim}") == any_(t.decisions.c.evidence))
                )
                | ((t.decisions.c.node == "nudge") & (t.decisions.c.chosen == dim)),
            )
        )
        declined = {r.session_id for r in rows if r.node == "plan_next"}
        rows = await conn.execute(
            select(t.decisions.c.session_id).where(
                t.decisions.c.user_id == ctx.user_id,
                t.decisions.c.node == "nudge",
                t.decisions.c.chosen == dim,
            )
        )
        nudged = {r.session_id for r in rows}
    streak = 0
    for session_id in sessions:
        if session_id in nudged:
            return False
        if session_id not in declined:
            break
        streak += 1
    return streak >= NUDGE_AFTER


async def _nudge(state: NajmaState, runtime: Runtime[NajmaContext], dim: str) -> Decision:
    ctx = runtime.context
    name = ctx.services.registry.dimension(dim).name.lower()
    text = (
        f"You've skipped {name} for a while. Want a short round, or should I stop suggesting it "
        "this week?"
    )
    decision = Decision(
        decision_id=uuid4(),
        node="nudge",
        at=datetime.now(UTC),
        question="Ask about a skill the user keeps turning down?",
        candidates=[],
        chosen=dim,
        reason=text,
        evidence=[f"declined:{dim}"],
    )
    await record_decision(ctx, decision)
    emit({"kind": "say", "text": text, "node": "nudge"})
    if runtime.store is not None:  # the pattern is worth remembering (UW3)
        # If Qdrant is down, the decision row still records the nudge.
        with contextlib.suppress(Exception):
            await runtime.store.aput(
                ("users", str(ctx.user_id), "episodic"),
                f"{ctx.session_id}-skips-{dim}",
                {
                    "text": f"Often skips {name}: turned it down {NUDGE_AFTER} sessions in a row",
                    "kind": "preference",
                    "importance": 0.7,
                    "dims": [dim],
                },
            )
    return decision


@traced("plan_next")
async def plan_next(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Choose the next skill and game with a utility whose parts are all shown (docs/plan/03).
    Code decides; a request from the user changes the inputs, never the rules."""
    ctx = runtime.context
    registry = ctx.services.registry
    by_dim = core_games_by_dim(registry)
    now = datetime.now(UTC)
    last_game = state.rounds[-1].game_id if state.rounds else None
    last_dims = set(registry.game(last_game).primary_dims) if last_game else set()
    fatigue = state.affect.fatigue_p if state.affect else 0.0
    intent = state.intent
    seed = ctx.seed + len(state.rounds)

    # What the user turned down or paused, and "something quick", narrow the pool; the policy
    # still ranks what's left (UW3).
    turned_down = list(intent.avoid_dims) if intent else []
    avoid = set(state.declined_dims) | set(turned_down) | await paused_dims(ctx, now)
    quick = bool(intent and intent.quick)
    skip_game = (
        state.exercise.game_id if intent and intent.replace_current and state.exercise else None
    )
    pool: dict[str, list[Game]] = {}
    for dim, games in by_dim.items():
        options = [g for g in games if g.id != skip_game and (not quick or g.duration_s <= QUICK_S)]
        if dim not in avoid and options:
            pool[dim] = options
    overridden = bool(pool) and (bool(turned_down) or quick or skip_game is not None)
    if not pool:
        pool = by_dim

    candidates: list[Candidate] = []
    for dim, games in pool.items():
        belief = _belief(state, dim)
        days = _days_since(belief, now)
        parts = {
            "uncertainty": belief.sigma / SIGMA_START,
            "staleness": 1.0 if days is None else min(days / STALENESS_CAP_DAYS, 1.0),
            "goal_weight": 1.0 if dim in state.goal_dims else 0.0,
            "plan_priority": 0.0,  # personal experiments, WP3.2
            "bandit_gain": 0.0,  # best-next-game bandit, WP3.3
            "fatigue_penalty": fatigue * (1.0 if max(g.duration_s for g in games) > 90 else 0.5),
            "repetition": 1.0 if dim in last_dims else 0.0,
        }
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        candidates.append(Candidate(option=dim, score=round(score, 4), breakdown=parts))
    candidates.sort(key=lambda c: c.score, reverse=True)

    update: dict[str, Any] = {}
    requested = registry.game(intent.game_id) if intent and intent.game_id else None
    wanted_dim = intent.dim if intent and intent.dim in by_dim else None
    force_assess = False
    if requested is not None:
        dim, game = requested.primary_dims[0], requested
        reason = f"You asked for {game.name}."
    elif wanted_dim is not None:
        dim = wanted_dim
        game = _pick(pool.get(dim, by_dim[dim]), last_game, seed)
        reason = f"You asked for {registry.dimension(dim).name.lower()}."
    elif overridden and not state.onboarding:
        dim = candidates[0].option
        game = _pick(pool[dim], last_game, seed)
        name = registry.dimension(dim).name.lower()
        reason = f"Sure. Here's {game.name}, a {_length(game)} {name} game, instead."
    elif state.onboarding:
        game = registry.game(state.onboarding[0])
        dim = game.primary_dims[0]
        total = len(state.onboarding) + len(state.rounds)
        reason = (
            f"Warm-up game {len(state.rounds) + 1} of {total}: {game.name}. "
            "Nothing here is a test you can fail."
        )
        update["onboarding"] = state.onboarding[1:]
        force_assess = True
    else:
        dim = candidates[0].option
        game = _pick(pool[dim], last_game, seed)
        belief = _belief(state, dim)
        name = registry.dimension(dim).name
        days = _days_since(belief, now)
        if belief.n == 0:
            reason = f"{name} is a skill I haven't measured yet."
        elif dim in state.goal_dims:
            reason = f"{name} is part of your goal, and it's the skill I'd learn most from now."
        else:
            when = "today" if days is not None and days < 1 else f"{days:.0f} days ago"
            reason = (
                f"{name} is the skill I'm least sure about right now, "
                f"and you last practised it {when}."
            )
        away = state.away_days
        if away is not None and away >= CHECKUP_AFTER_DAYS and len(state.rounds) < CHECKUP_ROUNDS:
            force_assess = True
            reason = (
                f"Welcome back. It's been {away:.0f} days, so I'm less sure about you than "
                f"before. A quick check-up: {name.lower()} first."
            )

    belief = _belief(state, dim)
    success_mode = "chill" if state.verdict == "ease" else state.success_mode
    mode = "assess" if force_assess else choose_mode(belief, success_mode)
    decision = Decision(
        decision_id=uuid4(),
        node="plan_next",
        at=now,
        question="Which skill and game next?",
        candidates=candidates[:3],
        chosen=f"{dim}:{game.id}",
        reason=reason,
        evidence=[f"declined:{d}" for d in turned_down] + (["quick"] if quick else []),
    )
    await record_decision(ctx, decision)
    if state.game_waiting() and state.exercise is not None:
        await _abandon(ctx, state.exercise.round_id)
    decisions = [decision]
    for declined_dim in turned_down:
        if await should_nudge(ctx, declined_dim):
            decisions.append(await _nudge(state, runtime, declined_dim))
    plan = SessionPlan(
        game_id=game.id,
        mode="assess" if mode == "assess" else "train",
        success_mode=success_mode,
        target_p=TARGET_P[mode],
        declined_dims=sorted(avoid - {dim}),
        goal_weights={d: 1.0 for d in state.goal_dims},
    )
    once: dict[str, Any] = {
        "game_id": None,
        "dim": None,
        "avoid_dims": [],
        "quick": False,
        "replace_current": False,
    }
    return {
        **update,
        "decisions": decisions,
        "plan": plan,
        "exercise": None,
        "declined_dims": turned_down,
        # A game or skill the user asked for is honoured once, not for the whole session.
        "intent": intent.model_copy(update=once) if intent else None,
    }


@traced("prepare_exercise")
async def prepare_exercise(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Exercise subgraph stand-in: pick the level, create the round row, build the spec.
    WP2.2 adds generated content, validation and the pool fallback."""
    ctx = runtime.context
    registry = ctx.services.registry
    assert state.plan is not None and state.plan.game_id
    game = registry.game(state.plan.game_id)
    belief = _belief(state, game.primary_dims[0])
    level = next_level(belief, state.plan.target_p)
    round_id = uuid4()
    async with ctx.services.engine.begin() as conn:
        played_before = (
            await conn.execute(
                select(func.count())
                .select_from(t.rounds)
                .where(t.rounds.c.user_id == ctx.user_id, t.rounds.c.game_id == game.id)
            )
        ).scalar_one()
        await start_round(
            conn,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            round_id=round_id,
            game_id=game.id,
            level=level,
        )
    knobs = knobs_for(game, level)
    seed = random.Random(f"{ctx.seed}:{round_id}").randrange(2**31)
    theme = state.intent.theme if state.intent else None
    content = None
    degraded: list[str] = []
    if ctx.services.content is not None and ctx.services.content.needs_content(game.id):
        content = await ctx.services.content.prepare(
            user_id=ctx.user_id,
            selection=ctx.llm,
            game_id=game.id,
            level=level,
            knobs=knobs,
            seed=seed,
            theme=theme,
        )
        degraded = content.degraded if content else []
    spec = ExerciseSpec(
        round_id=round_id,
        game_id=game.id,
        mode=state.plan.mode,
        target_p=state.plan.target_p,
        level=level,
        difficulty_b=b_for_level(level),
        knobs=knobs,
        content=content.content if content else None,
        content_item_id=content.item_id if content else None,
        theme=theme,
        seed=seed,
        practice_trials=game.practice_trials if played_before == 0 else 0,
        duration_s=game.duration_s,
        reason=state.decisions[-1].reason if state.decisions else "Next round.",
    )
    return {"exercise": spec, "degraded": degraded} if degraded else {"exercise": spec}


async def play(state: NajmaState, *, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """The pause: the browser plays the exercise and resumes with a RoundResult."""
    assert state.exercise is not None
    value = interrupt({"type": "exercise", "spec": state.exercise.model_dump(mode="json")})
    return {"rounds": [RoundResult.model_validate(value)]}


@traced("score_update")
async def score_update(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    ctx = runtime.context
    result = state.rounds[-1]
    scored = await score_round_tx(ctx.services.engine, ctx.user_id, result, ctx.services.registry)
    async with ctx.services.engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    func.count().filter(t.trials.c.correct.is_(True)),
                    func.count().filter(t.trials.c.correct.is_not(None)),
                ).where(t.trials.c.round_id == result.round_id, t.trials.c.practice.is_(False))
            )
        ).one()
    accuracy = row[0] / row[1] if row[1] else None
    summary = RoundSummary(
        round_id=str(result.round_id),
        game_id=result.game_id,
        status=result.status,
        mean_score=scored.outcome.mean_score if scored else None,
        accuracy=accuracy,
        correct=int(row[0]),
        answered=int(row[1]),
        observations=scored.outcome.observations if scored else 0,
        changes=scored.changes if scored else [],
        quality_verdict=scored.outcome.quality.verdict if scored else "ok",
    )
    return {"last_round": summary, "twin": await read_twin_snapshot(ctx)}


FATIGUE_Z = 1.5  # docs/plan/10: a sustained rise past 1.5 SD against the session's start
FRUSTRATION_P = 0.7


async def session_fatigue(ctx: NajmaContext) -> float:
    """P1 rule: compare the latest answers with the first ones in this session. Slower answers
    (z > 1.5) together with more errors suggest fatigue. Behaviour only (docs/plan/12)."""
    async with ctx.services.engine.connect() as conn:
        rows = (
            await conn.execute(
                select(t.trials.c.rt_ms, t.trials.c.correct)
                .where(
                    t.trials.c.session_id == ctx.session_id,
                    t.trials.c.practice.is_(False),
                    t.trials.c.rt_ms.is_not(None),
                )
                .order_by(t.trials.c.ts)
            )
        ).all()
    if len(rows) < 24:
        return 0.0
    third = len(rows) // 3
    early, late = rows[:third], rows[-third:]
    rts = [float(r.rt_ms) for r in early]
    mean = sum(rts) / len(rts)
    sd = (sum((x - mean) ** 2 for x in rts) / max(1, len(rts) - 1)) ** 0.5 or 1.0
    z = (sum(float(r.rt_ms) for r in late) / len(late) - mean) / sd
    errors_early = sum(r.correct is False for r in early) / len(early)
    errors_late = sum(r.correct is False for r in late) / len(late)
    return 0.8 if z > FATIGUE_Z and errors_late > errors_early else min(0.5, max(0.0, z / 4))


async def _log_affect(ctx: NajmaContext, affect: AffectReading, now: datetime) -> None:
    """affect.estimated goes to the event log only; nothing reads it into the profile."""
    async with ctx.services.engine.begin() as conn:
        await append_event(
            conn,
            AffectEstimated(user_id=ctx.user_id, session_id=ctx.session_id, ts=now, payload=affect),
        )


@traced("monitor")
async def monitor(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    """Continue, ease off, suggest a break, or stop (docs/plan/03, monitor routing)."""
    now = datetime.now(UTC)
    rounds = state.rounds
    last = rounds[-1] if rounds else None
    stopped = sum(1 for r in rounds if r.status == "stopped")
    accuracy = state.last_round.accuracy if state.last_round else None
    affect = estimate(last, accuracy, await session_fatigue(runtime.context))
    frustration, fatigue = affect.frustration_p, affect.fatigue_p
    await _log_affect(runtime.context, affect, now)
    minutes = (now - state.started_at).total_seconds() / 60 if state.started_at else 0.0
    budget = state.budget
    verdict: Verdict
    if frustration > FRUSTRATION_P or stopped >= 2:
        if len(rounds) < budget.max_rounds and stopped < 2:
            verdict, reason = "ease", "That one looked tough. Let's do something lighter."
        else:
            verdict, reason = "break", "That one looked tough. A short break would help."
    elif fatigue >= 0.8:
        verdict = "end"
        reason = "Your answers are slowing down compared with the start. Good place to stop."
    elif budget.fatigue_point_min and minutes > budget.fatigue_point_min:
        verdict = "end"
        reason = (
            f"Your speed usually drops after about {budget.fatigue_point_min:.0f} minutes. "
            "Good place to stop."
        )
    elif len(rounds) >= budget.max_rounds:
        verdict, reason = "end", f"That's {len(rounds)} rounds. Nice session."
    elif budget.max_minutes and minutes > budget.max_minutes:
        verdict, reason = "end", "That's enough for today. Nice session."
    else:
        verdict, reason = "continue", "Ready for the next round."
    decision = Decision(
        decision_id=uuid4(),
        node="monitor",
        at=now,
        question="Continue, ease off, take a break or stop?",
        candidates=[
            Candidate(option=v, score=float(v == verdict), breakdown={})
            for v in ("continue", "ease", "break", "end")
        ],
        chosen=verdict,
        reason=reason,
        evidence=[str(last.round_id)] if last else [],
    )
    await record_decision(runtime.context, decision)
    return {"verdict": verdict, "decisions": [decision], "affect": affect}
