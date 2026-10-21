"""The play loop: plan_next -> prepare_exercise -> play (pause) -> score_update -> monitor
(docs/plan/03). Code decides; nothing here asks an LLM what to do."""

import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import func, select

from backend.agent.context import NajmaContext
from backend.agent.nodes.perceive import read_twin_snapshot
from backend.agent.state import NajmaState
from backend.agent.telemetry import record_decision, traced
from backend.contracts.decision import Candidate, Decision
from backend.contracts.exercise import ExerciseSpec, RoundResult
from backend.contracts.session import RoundSummary, SessionPlan, Verdict
from backend.db import tables as t
from backend.db.twin_store import score_round_tx, start_round
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


@traced("plan_next")
async def plan_next(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    ctx = runtime.context
    registry = ctx.services.registry
    by_dim = core_games_by_dim(registry)
    now = datetime.now(UTC)
    last_game = state.rounds[-1].game_id if state.rounds else None
    last_dims = set(registry.game(last_game).primary_dims) if last_game else set()
    fatigue = state.affect.fatigue_p if state.affect else 0.0
    intent = state.intent

    requested: Game | None = None
    if intent and intent.game_id:
        requested = registry.game(intent.game_id)
    candidates: list[Candidate] = []
    for dim, games in by_dim.items():
        belief = _belief(state, dim)
        days = _days_since(belief, now)
        parts = {
            "uncertainty": belief.sigma / SIGMA_START,
            "staleness": 1.0 if days is None else min(days / STALENESS_CAP_DAYS, 1.0),
            "goal_weight": 0.0,
            "plan_priority": 0.0,
            "bandit_gain": 0.0,
            "fatigue_penalty": fatigue * (1.0 if max(g.duration_s for g in games) > 90 else 0.5),
            "repetition": 1.0 if dim in last_dims else 0.0,
        }
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        candidates.append(Candidate(option=dim, score=round(score, 4), breakdown=parts))
    candidates.sort(key=lambda c: c.score, reverse=True)

    wanted_dim = intent.dim if intent and intent.dim in by_dim else None
    if requested is not None:
        dim = requested.primary_dims[0]
        game = requested
        reason = f"You asked for {game.name}."
    elif wanted_dim is not None:
        dim = wanted_dim
        options = [g for g in by_dim[dim] if g.id != last_game] or by_dim[dim]
        game = random.Random(ctx.seed + len(state.rounds)).choice(options)
        reason = f"You asked for {registry.dimension(dim).name.lower()}."
    else:
        dim = candidates[0].option
        options = [g for g in by_dim[dim] if g.id != last_game] or by_dim[dim]
        game = random.Random(ctx.seed + len(state.rounds)).choice(options)
        belief = _belief(state, dim)
        name = registry.dimension(dim).name
        days = _days_since(belief, now)
        if belief.n == 0:
            reason = f"{name} is a skill I haven't measured yet."
        else:
            when = "today" if days is not None and days < 1 else f"{days:.0f} days ago"
            reason = (
                f"{name} is the skill I'm least sure about right now, "
                f"and you last practised it {when}."
            )

    belief = _belief(state, dim)
    success_mode = "chill" if state.verdict == "ease" else state.success_mode
    mode = choose_mode(belief, success_mode)
    target = TARGET_P[mode]
    decision = Decision(
        decision_id=uuid4(),
        node="plan_next",
        at=now,
        question="Which skill and game next?",
        candidates=candidates[:3],
        chosen=f"{dim}:{game.id}",
        reason=reason,
        evidence=[],
    )
    await record_decision(ctx, decision)
    plan = SessionPlan(
        game_id=game.id,
        mode="assess" if mode == "assess" else "train",
        success_mode=success_mode,
        target_p=target,
    )
    return {
        "decisions": [decision],
        "plan": plan,
        "exercise": None,
        # A game or skill the user asked for is honoured once, not for the whole session.
        "intent": intent.model_copy(update={"game_id": None, "dim": None}) if intent else None,
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
    spec = ExerciseSpec(
        round_id=round_id,
        game_id=game.id,
        mode=state.plan.mode,
        target_p=state.plan.target_p,
        level=level,
        difficulty_b=b_for_level(level),
        knobs=knobs_for(game, level),
        theme=state.intent.theme if state.intent else None,
        seed=random.Random(f"{ctx.seed}:{round_id}").randrange(2**31),
        practice_trials=game.practice_trials if played_before == 0 else 0,
        duration_s=game.duration_s,
        reason=state.decisions[-1].reason if state.decisions else "Next round.",
    )
    return {"exercise": spec}


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


@traced("monitor")
async def monitor(state: NajmaState, runtime: Runtime[NajmaContext]) -> dict[str, Any]:
    now = datetime.now(UTC)
    rounds = state.rounds
    last = rounds[-1] if rounds else None
    stopped = sum(1 for r in rounds if r.status == "stopped")
    frustrated = last is not None and (
        last.stop_reason == "frustration"
        or last.status == "eased"
        or (state.last_round is not None and (state.last_round.accuracy or 1.0) < 0.4)
    )
    minutes = (now - state.started_at).total_seconds() / 60 if state.started_at else 0.0
    budget = state.budget
    verdict: Verdict
    if frustrated or stopped >= 2:
        if len(rounds) < budget.max_rounds:
            verdict, reason = "ease", "That one looked tough. Let's do something lighter."
        else:
            verdict, reason = "break", "That one looked tough. A short break would help."
    elif budget.fatigue_point_min and minutes > budget.fatigue_point_min:
        verdict = "end"
        reason = (
            f"Your speed usually drops after about {budget.fatigue_point_min:.0f} minutes. "
            "Good place to stop."
        )
    elif len(rounds) >= budget.max_rounds:
        verdict, reason = "end", f"That's {len(rounds)} rounds. Nice session."
    else:
        verdict, reason = "continue", "Ready for the next round."
    decision = Decision(
        decision_id=uuid4(),
        node="monitor",
        at=now,
        question="Continue, ease off, take a break or stop?",
        candidates=[
            Candidate(option=v, score=float(v == verdict))
            for v in ("continue", "ease", "break", "end")
        ],
        chosen=verdict,
        reason=reason,
        evidence=[str(last.round_id)] if last else [],
    )
    await record_decision(runtime.context, decision)
    return {"verdict": verdict, "decisions": [decision]}
