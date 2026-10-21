"""The play loop: plan_next -> prepare_exercise -> play (pause) -> score_update -> monitor
(docs/plan/03). Code decides; nothing here asks an LLM what to do."""

import contextlib
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import numpy as np
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import any_, func, literal, select

from backend.agent import experiments
from backend.agent.affect import estimate, recent_cues
from backend.agent.context import NajmaContext
from backend.agent.nodes.perceive import read_twin_snapshot
from backend.agent.nodes.talk import emit_reply
from backend.agent.state import NajmaState
from backend.agent.telemetry import emit, record_decision, traced
from backend.contracts.affect import AffectReading, AffectSource
from backend.contracts.decision import Candidate, Decision
from backend.contracts.events import AffectEstimated
from backend.contracts.exercise import ExerciseSpec, RoundResult
from backend.contracts.session import RoundSummary, SessionPlan, Verdict
from backend.db import tables as t
from backend.db.twin_store import append_event, score_round_tx, start_round
from backend.ml import bandit
from backend.registry.models import Game, Registry
from backend.scoring.kalman_elo import SIGMA_START, Belief
from backend.scoring.levels import TARGET_P, b_for_level, choose_mode, knobs_for, next_level
from backend.scoring.loadings import recipe_loadings

# docs/plan/03, "How plan_next decides". bandit_gain is the best-next-game bandit
# (backend/ml/bandit.py); it stays 0 until the person has played enough rounds.
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


def allowed(game: Game, consent: frozenset[str] | None) -> bool:
    """A game that needs a consent switch (planted mistakes) only runs with it on."""
    return game.consent is None or consent is None or game.consent in consent


def core_games_by_dim(
    registry: Registry, consent: frozenset[str] | None = None
) -> dict[str, list[Game]]:
    """Core games the browser can run, by primary skill, leaving out games a switch has turned
    off. Custom block games are only served when asked for."""
    out: dict[str, list[Game]] = {}
    for game in registry.games:
        if (
            game.phase == "P1"
            and game.kind == "game"
            and game.origin != "custom"
            and game.available
            and allowed(game, consent)
        ):
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


def _best(options: list[Game], last_game: str | None, samples: dict[str, float]) -> Game | None:
    """The game with the best bandit sample (not the one just played), or None without data."""
    choices = [g for g in options if g.id != last_game] or options
    if not samples or not choices:
        return None
    return max(choices, key=lambda g: samples.get(g.id, float("-inf")))


async def _bandit_samples(
    ctx: NajmaContext, state: NajmaState, pool: dict[str, list[Game]]
) -> dict[str, float]:
    """One Thompson sample per game on offer (docs/plan/10, section 4); empty until there is
    data that says something (everyone's rounds, or enough of the person's own)."""
    registry = ctx.services.registry
    async with ctx.services.engine.connect() as conn:
        gains = await bandit.gains_by_game(conn, ctx.user_id, registry)
    priors = await bandit.population(ctx.services.engine, registry)
    if not bandit.ready(gains, priors):
        return {}
    games = {g.id for options in pool.values() for g in options}
    rng = np.random.default_rng([ctx.seed, len(state.rounds), ctx.session_id.int % 2**32])
    return bandit.thompson(bandit.arms(gains, games, priors), rng)


QUICK_S = 60  # "something quick": games of a minute or less
EASED_ROUNDS = 2  # a session offered to someone drifting away
NUDGE_AFTER = 3  # UW3: sessions in a row a skill was turned down before Najma asks once


def _length(game: Game) -> str:
    s = game.duration_s
    return f"{s // 60}-minute" if s % 60 == 0 else f"{s}-second"


def _themed_game(registry: Registry, pool: dict[str, list[Game]], intent: Any) -> Game | None:
    """UW4, "a memory game about football": a game that can take the theme, from the skill
    asked for or its group in the sky (memory: working or short-term), else any."""
    if intent is None or not intent.theme:
        return None
    games = [g for options in pool.values() for g in options if g.themable]
    if intent.dim:
        group = registry.dimension(intent.dim).group
        near = [g for g in games if registry.dimension(g.primary_dims[0]).group == group]
        games = near or games
    return games[0] if games else None


def _callback_due(
    registry: Registry, state: NajmaState, consent: frozenset[str] | None, avoid: set[str]
) -> bool:
    """Callback recalls this session's Market List once its delay has passed, once a session."""
    game = registry.game("callback")
    if not game.available or not allowed(game, consent) or game.primary_dims[0] in avoid:
        return False
    if any(r.game_id == game.id for r in state.rounds):
        return False
    delay = timedelta(minutes=knobs_for(game, 0.0)["delay_min"])
    now = datetime.now(UTC)
    return any(
        r.game_id == "market_list" and r.status != "stopped" and now - r.ended_at >= delay
        for r in state.rounds
    )


async def _market_list_words(ctx: NajmaContext) -> list[str]:
    """The words of this session's latest Market List round, in the order they were shown."""
    async with ctx.services.engine.connect() as conn:
        rows = (
            await conn.execute(
                select(t.trials.c.round_id, t.trials.c.stimulus)
                .where(
                    t.trials.c.user_id == ctx.user_id,
                    t.trials.c.session_id == ctx.session_id,
                    t.trials.c.game_id == "market_list",
                    t.trials.c.practice.is_(False),
                )
                .order_by(t.trials.c.ts)
            )
        ).all()
    if not rows:
        return []
    latest = [r.stimulus for r in rows if r.round_id == rows[-1].round_id]
    return [s["word"] for s in sorted(latest, key=lambda s: s["position"])]


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
    by_dim = core_games_by_dim(registry, ctx.consent)
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

    samples = await _bandit_samples(ctx, state, pool)
    bandit_by_dim = bandit.skill_gains(
        samples, {d: [g.id for g in games] for d, games in pool.items()}
    )
    candidates: list[Candidate] = []
    for dim, games in pool.items():
        belief = _belief(state, dim)
        days = _days_since(belief, now)
        parts = {
            "uncertainty": belief.sigma / SIGMA_START,
            "staleness": 1.0 if days is None else min(days / STALENESS_CAP_DAYS, 1.0),
            "goal_weight": 1.0 if dim in state.goal_dims else 0.0,
            "plan_priority": 0.0,  # personal experiments, WP3.2
            "bandit_gain": bandit_by_dim.get(dim, 0.0),
            "fatigue_penalty": fatigue * (1.0 if max(g.duration_s for g in games) > 90 else 0.5),
            "repetition": 1.0 if dim in last_dims else 0.0,
        }
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        candidates.append(Candidate(option=dim, score=round(score, 4), breakdown=parts))
    candidates.sort(key=lambda c: c.score, reverse=True)

    update: dict[str, Any] = {}
    evidence: list[str] = []
    requested = registry.game(intent.game_id) if intent and intent.game_id else None
    themed = _themed_game(registry, pool, intent) if requested is None else None
    experiment = None
    if requested is None and themed is None and not state.onboarding:
        slot = await experiment_slot(ctx)
        if slot is not None:
            played = {r.game_id for r in state.rounds}
            if any(g not in played for g in slot[0].design["games"]):
                experiment = slot
    switched_off = requested is not None and not allowed(requested, ctx.consent)
    if switched_off:
        requested = None
    no_list = (
        requested is not None
        and requested.id == "callback"
        and not any(r.game_id == "market_list" for r in state.rounds)
    )
    if no_list:
        requested = None
    wanted_dim = intent.dim if intent and intent.dim in by_dim else None
    force_assess = False
    if switched_off and intent and intent.game_id:
        dim = candidates[0].option
        game = _pick(pool[dim], last_game, seed)
        off = registry.game(intent.game_id).name
        reason = f"{off} is switched off in your privacy settings, so here's {game.name} instead."
    elif no_list:
        game = registry.game("market_list")
        dim = game.primary_dims[0]
        reason = "Callback asks about a Market List from earlier, so let's start with Market List."
    elif requested is not None and requested.origin == "custom":
        dim, game = requested.primary_dims[0], requested
        # docs/plan/08: block-built games count at low weight, and Najma says so.
        reason = (
            "Fun idea. I'll build it from my game blocks. "
            "I'm only counting it a little until it's been tested more."
        )
    elif requested is not None:
        dim, game = requested.primary_dims[0], requested
        reason = f"You asked for {game.name}."
    elif themed is not None and intent is not None and intent.theme:
        dim, game = themed.primary_dims[0], themed
        kind = registry.dimension(intent.dim).group if intent.dim else "game"
        reason = f"{intent.theme.capitalize()} {kind}, coming up: {game.name}."
    elif wanted_dim is not None:
        dim = wanted_dim
        game = _pick(pool.get(dim, by_dim[dim]), last_game, seed)
        reason = f"You asked for {registry.dimension(dim).name.lower()}."
    elif experiment is not None:
        row, window = experiment
        played = {r.game_id for r in state.rounds}
        todo = [g for g in row.design["games"] if g not in played]
        game = registry.game(todo[0])
        dim = game.primary_dims[0]
        n = len(row.design["games"])
        reason = (
            f"Experiment session ({window}), game {n - len(todo) + 1} of {n}: {game.name}. "
            "Same games every time, so morning and evening can be compared fairly."
        )
    elif overridden and not state.onboarding:
        dim = candidates[0].option
        game = _best(pool[dim], last_game, samples) or _pick(pool[dim], last_game, seed)
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
    elif _callback_due(registry, state, ctx.consent, avoid):
        game = registry.game("callback")
        dim = game.primary_dims[0]
        reason = (
            "Earlier you learned a market list. Let's see which words you still remember: Callback."
        )
    else:
        dim = candidates[0].option
        easing = not state.rounds and state.engagement is not None and state.engagement.high_risk
        options = pool[dim]
        if easing:  # drifting away: something short and easy (docs/plan/10, section 2)
            options = [g for g in options if g.duration_s <= QUICK_S] or options
        game = _best(options, last_game, samples) or _pick(options, last_game, seed)
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
        if easing and state.engagement is not None:
            reason = (
                f"A short, easy session today: {game.name}, a {_length(game)} "
                f"{name.lower()} game. Two rounds and we're done."
            )
            update["budget"] = state.budget.model_copy(
                update={"max_rounds": min(state.budget.max_rounds, EASED_ROUNDS)}
            )
            evidence.append(
                f"engagement_risk:{state.engagement.low:.2f}-{state.engagement.high:.2f}"
            )
        away = state.away_days
        # Someone drifting away gets the short, easy session; the check-up can wait.
        if (
            away is not None
            and away >= CHECKUP_AFTER_DAYS
            and not easing
            and len(state.rounds) < CHECKUP_ROUNDS
        ):
            force_assess = True
            reason = (
                f"Welcome back. It's been {away:.0f} days, so I'm less sure about you than "
                f"before. A quick check-up: {name.lower()} first."
            )

    belief = _belief(state, dim)
    eased = state.verdict == "ease" or any(e.startswith("engagement_risk:") for e in evidence)
    success_mode = "chill" if eased else state.success_mode
    mode = "assess" if force_assess else choose_mode(belief, success_mode)
    if not state.rounds and state.fatigue_point is not None:
        budget = update.get("budget", state.budget)
        update["budget"] = budget.model_copy(
            update={"fatigue_point_min": state.fatigue_point.median}
        )
    decision = Decision(
        decision_id=uuid4(),
        node="plan_next",
        at=now,
        question="Which skill and game next?",
        candidates=candidates[:3],
        chosen=f"{dim}:{game.id}",
        reason=reason,
        evidence=[f"declined:{d}" for d in turned_down] + (["quick"] if quick else []) + evidence,
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
            # A custom game is built from what the user asked for (docs/plan/08).
            request=state.intent.text if state.intent and game.origin == "custom" else None,
        )
        degraded = content.degraded if content else []
    # A custom game counts for the skills its recipe names, not the registry's placeholder.
    loadings = (
        recipe_loadings(content.content, registry) if content and game.origin == "custom" else None
    )
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
            loadings=loadings,
        )
    words = await _market_list_words(ctx) if game.id == "callback" else []
    spec = ExerciseSpec(
        round_id=round_id,
        game_id=game.id,
        mode=state.plan.mode,
        target_p=state.plan.target_p,
        level=level,
        difficulty_b=b_for_level(level),
        knobs=knobs,
        content=content.content if content else ({"words": words} if words else None),
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
    await _experiment_round_done(runtime)
    return {"last_round": summary, "twin": await read_twin_snapshot(ctx)}


async def experiment_slot(ctx: NajmaContext) -> tuple[Any, str] | None:
    """The running experiment and this session's window (morning or evening), when this session
    counts toward it (docs/plan/09, Personal experiments)."""
    async with ctx.services.engine.connect() as conn:
        row = await experiments.running(conn, ctx.user_id)
        if row is None:
            return None
        hour = (
            await conn.execute(
                select(
                    func.extract("hour", func.timezone(t.users.c.timezone, t.sessions.c.started_at))
                )
                .select_from(t.sessions.join(t.users, t.users.c.user_id == t.sessions.c.user_id))
                .where(t.sessions.c.session_id == ctx.session_id)
            )
        ).scalar_one()
    window = experiments.window_of(int(hour))
    if window is None or any(
        s["session_id"] == str(ctx.session_id) for s in row.result["sessions"]
    ):
        return None
    if experiments.progress(row)[window] >= row.design["sessions_per_condition"]:
        return None
    return row, window


async def _experiment_round_done(runtime: Runtime[NajmaContext]) -> None:
    """When this session has played every experiment game, log it; when both windows are full,
    close the experiment and tell the user what it found (with its facts)."""
    ctx = runtime.context
    slot = await experiment_slot(ctx)
    if slot is None:
        return
    row, window = slot
    games = row.design["games"]
    async with ctx.services.engine.begin() as conn:
        scores = {
            r.game_id: float(r.score)
            for r in await conn.execute(
                select(t.rounds.c.game_id, t.rounds.c.score).where(
                    t.rounds.c.session_id == ctx.session_id,
                    t.rounds.c.game_id.in_(games),
                    t.rounds.c.score.is_not(None),
                )
            )
        }
        if set(games) - set(scores):
            return
        comparison = await experiments.log_session(
            conn, row, ctx.user_id, ctx.session_id, window, sum(scores.values()) / len(scores)
        )
    if comparison is None:
        emit(
            {
                "kind": "say",
                "text": f"That was an experiment session ({window}). Thanks!",
                "node": "experiment",
            }
        )
        return
    packet, text = experiments.result_facts(comparison)
    emit_reply(text, packet, "experiment")
    memory = ctx.services.memory
    if memory is not None and comparison.verdict != "inconclusive":
        with contextlib.suppress(Exception):  # the result is in Postgres either way
            await memory.write(
                ctx.user_id,
                f"Does better in the {comparison.verdict} (experiment, probability "
                f"{max(comparison.p_evening_better, 1 - comparison.p_evening_better):.2f})",
                collection="facts",
                kind="preference",
                importance=0.8,
            )


FATIGUE_Z = 1.5  # docs/plan/10: a sustained rise past 1.5 SD against the session's start
FRUSTRATION_P = 0.7
CUE_WINDOW = timedelta(minutes=10)  # server clock: browser clocks drift


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
    ctx = runtime.context
    fatigue_now = await session_fatigue(ctx)
    # Easing and stopping follow behaviour alone. Optional camera and voice cues (fused at 0.3 at
    # most) can only add a break suggestion and soften the coach's tone (docs/plan/12).
    behaviour = estimate(last, accuracy, fatigue_now)
    frustration, fatigue = behaviour.frustration_p, behaviour.fatigue_p
    cues: list[tuple[AffectSource, float]] = []
    if last is not None and ctx.consent & {"camera", "voice_tone"}:
        async with ctx.services.engine.connect() as conn:
            since = now - CUE_WINDOW
            cues = await recent_cues(conn, ctx.user_id, ctx.session_id, since, ctx.consent)
    affect = estimate(last, accuracy, fatigue_now, cues) if cues else behaviour
    await _log_affect(ctx, affect, now)
    minutes = (now - state.started_at).total_seconds() / 60 if state.started_at else 0.0
    budget = state.budget
    verdict: Verdict
    if frustration > FRUSTRATION_P or stopped >= 2:
        if len(rounds) < budget.max_rounds and stopped < 2:
            verdict, reason = "ease", "That one looked tough. Let's do something lighter."
        else:
            verdict, reason = "break", "That one looked tough. A short break would help."
    elif affect.frustration_p > FRUSTRATION_P and len(rounds) < budget.max_rounds:
        verdict, reason = "break", "That one looked tough. A short break could help."
    elif fatigue >= 0.8:
        verdict = "end"
        reason = "Your answers are slowing down compared with the start. Good place to stop."
    elif budget.fatigue_point_min and minutes > budget.fatigue_point_min:
        verdict = "end"
        point = state.fatigue_point
        when = (
            f"{point.low:.0f} to {point.high:.0f} minutes"
            if point is not None and round(point.low) < round(point.high)
            else f"about {budget.fatigue_point_min:.0f} minutes"
        )
        reason = (
            f"Your answers usually start to slow down {when} into a session. Good place to stop."
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
