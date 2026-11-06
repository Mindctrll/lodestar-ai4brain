"""The record and the profile: trial ingestion, the scored-round transaction, rebuild and reads
(docs/plan/04, "How writes work"; AGENTS.md rule 6).

A scored round is one transaction holding a per-user advisory lock: events, round status,
dimension state, history and learned item difficulty change together or not at all.
"""

import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.acs.events import Observation, from_trials, iteration, pushback
from backend.contracts.acs import AcsEvent
from backend.contracts.events import (
    AcsObserved,
    AssessmentContested,
    ContestPayload,
    DimensionChange,
    HistoryRow,
    RoundCompleted,
    ScoringInputs,
    TrialRecorded,
    TwinUpdated,
    TwinUpdatedPayload,
    parse_event,
)
from backend.contracts.exercise import RoundResult
from backend.contracts.trial import TrialEvent
from backend.contracts.views import (
    STILL_LEARNING_SIGMA,
    CurvePoint,
    DimensionView,
    IngestResult,
    TwinView,
)
from backend.db import tables as t
from backend.registry.models import Registry
from backend.scoring.kalman_elo import Belief, drift, update_item_difficulty, widen
from backend.scoring.loadings import loading_matrix
from backend.scoring.norms import Norms
from backend.scoring.priors import cold_start
from backend.scoring.quality import FLAGGED, TAP_IN_TIME, device_lag
from backend.scoring.rounds import RoundOutcome, score_round

NOTIFY_CHANNEL = "twin_updated"
LAG_TAPS = 16  # the latest calibration's taps
# Rushed or contested answers: the estimate stays put and its range gets wider.
FLAGGED_WIDEN = 1.35
CONTEST_WIDEN = 1.35


class RoundNotFound(LookupError):
    pass


class ForeignRound(PermissionError):
    pass


def level_key(level: float) -> str:
    return f"{level:.2f}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def lock_user(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:u))"), {"u": str(user_id)})


async def user_scope(conn: AsyncConnection, user_id: UUID) -> None:
    """Row-level security (migration 0007): the rest of this transaction runs as lodestar_app and
    sees and writes only this user's rows, so a missing `user_id` filter can't leak another's."""
    await conn.execute(text("SET LOCAL ROLE lodestar_app"))
    await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


async def append_event(conn: AsyncConnection, event: Any) -> UUID:
    """Insert one contract event into twin.events (append-only) and return its id."""
    row = await conn.execute(
        t.events.insert()
        .values(
            user_id=event.user_id,
            session_id=event.session_id,
            ts=event.ts,
            type=event.type,
            schema_version=event.schema_version,
            payload=event.payload.model_dump(mode="json"),
        )
        .returning(t.events.c.event_id)
    )
    event_id: UUID = row.scalar_one()
    return event_id


# Users and tokens -------------------------------------------------------------------------


async def create_user(
    conn: AsyncConnection,
    *,
    display_name: str | None = None,
    persona: str = "willow",
    timezone: str | None = None,
    age_confirmed: bool = False,
) -> tuple[UUID, str]:
    values: dict[str, str | bool | None] = {
        "display_name": display_name,
        "persona": persona,
        "age_confirmed": age_confirmed,
    }
    if timezone:
        values["timezone"] = timezone
    user_id: UUID = (
        await conn.execute(t.users.insert().values(**values).returning(t.users.c.user_id))
    ).scalar_one()
    token = secrets.token_urlsafe(32)
    await conn.execute(t.user_tokens.insert().values(token_hash=hash_token(token), user_id=user_id))
    return user_id, token


async def user_for_token(conn: AsyncConnection, token: str) -> UUID | None:
    row = await conn.execute(
        t.user_tokens.update()
        .where(t.user_tokens.c.token_hash == hash_token(token))
        .values(last_used=func.now())
        .returning(t.user_tokens.c.user_id)
    )
    user_id: UUID | None = row.scalar_one_or_none()
    return user_id


# Rounds and trials ------------------------------------------------------------------------


async def start_round(
    conn: AsyncConnection,
    *,
    user_id: UUID,
    session_id: UUID,
    round_id: UUID,
    game_id: str,
    level: float,
    loadings: dict[str, float] | None = None,
) -> None:
    """Create the round when the exercise is issued, so trials can reference it (UW6).
    `loadings` overrides the game's registry loadings (a custom game's recipe)."""
    await conn.execute(
        pg_insert(t.rounds)
        .values(
            round_id=round_id,
            user_id=user_id,
            session_id=session_id,
            game_id=game_id,
            level=level,
            loadings=loadings,
        )
        .on_conflict_do_nothing(index_elements=["round_id"])
    )


async def record_trials(
    conn: AsyncConnection, user_id: UUID, trials: Sequence[TrialEvent]
) -> IngestResult:
    """Append trial events and their typed copies. Retries of the same trial are ignored."""
    round_ids = {tr.round_id for tr in trials}
    owners = await conn.execute(
        select(t.rounds.c.round_id, t.rounds.c.user_id).where(t.rounds.c.round_id.in_(round_ids))
    )
    owner_by_round = {r.round_id: r.user_id for r in owners}
    for round_id in round_ids:
        if round_id not in owner_by_round:
            raise RoundNotFound(str(round_id))
        if owner_by_round[round_id] != user_id:
            raise ForeignRound(str(round_id))

    accepted = 0
    for trial in trials:
        inserted = await conn.execute(
            pg_insert(t.trials)
            .values(
                trial_id=trial.trial_id,
                user_id=user_id,
                session_id=trial.session_id,
                round_id=trial.round_id,
                game_id=trial.game_id,
                level=trial.level,
                trial_index=trial.trial_index,
                practice=trial.practice,
                correct=trial.correct,
                rt_ms=trial.rt_ms,
                hint_level=trial.hint_level,
                confidence=trial.confidence,
                stimulus=trial.stimulus,
                response=trial.response,
                ts=trial.ts,
            )
            .on_conflict_do_nothing(index_elements=["trial_id"])
            .returning(t.trials.c.trial_id)
        )
        if inserted.scalar_one_or_none() is None:
            continue
        accepted += 1
        await append_event(
            conn,
            TrialRecorded(user_id=user_id, session_id=trial.session_id, ts=trial.ts, payload=trial),
        )
    return IngestResult(accepted=accepted, duplicates=len(trials) - accepted)


def _trial_from_row(row: Any) -> TrialEvent:
    return TrialEvent(
        trial_id=row.trial_id,
        round_id=row.round_id,
        session_id=row.session_id,
        game_id=row.game_id,
        level=row.level,
        trial_index=row.trial_index,
        practice=row.practice,
        stimulus=row.stimulus,
        response=row.response,
        correct=row.correct,
        rt_ms=row.rt_ms,
        hint_level=row.hint_level,
        confidence=row.confidence,
        ts=row.ts,
    )


# The scored round -------------------------------------------------------------------------


async def calibrated_lag(conn: AsyncConnection, user_id: UUID) -> float:
    """The user's device lag from their latest tap-in-time taps (Quick Draw), 0 if none."""
    offsets = (
        await conn.execute(
            select(t.trials.c.response["offset_ms"].as_float())
            .where(
                t.trials.c.user_id == user_id,
                t.trials.c.stimulus["kind"].as_string() == TAP_IN_TIME,
                t.trials.c.response.is_not(None),
            )
            .order_by(t.trials.c.ts.desc())
            .limit(LAG_TAPS)
        )
    ).scalars()
    return device_lag([o for o in offsets if o is not None])


@dataclass(frozen=True)
class ScoredRound:
    round_id: UUID
    outcome: RoundOutcome
    changes: list[DimensionChange]
    twin_event_id: UUID


async def score_round_tx(
    engine: AsyncEngine,
    user_id: UUID,
    result: RoundResult,
    registry: Registry,
    *,
    now: datetime | None = None,
) -> ScoredRound | None:
    """Score a finished round in one transaction. Returns None if it was already scored
    (a duplicate resume), so calling this twice changes nothing."""
    now = now or datetime.now(UTC)
    async with engine.begin() as conn:
        await lock_user(conn, user_id)
        await user_scope(conn, user_id)
        round_row = (
            await conn.execute(
                select(t.rounds)
                .where(t.rounds.c.round_id == result.round_id, t.rounds.c.user_id == user_id)
                .with_for_update()
            )
        ).one_or_none()
        if round_row is None:
            raise RoundNotFound(str(result.round_id))
        if round_row.scored_at is not None:
            return None

        game = registry.game(round_row.game_id)
        loads: dict[str, float] = dict(
            round_row.loadings or loading_matrix(registry).get(game.id, {})
        )
        # A refresh mid-game replays the round from the start (UW6): for each trial index the
        # latest answer wins, so the unfinished attempt isn't counted twice.
        latest = {
            r.trial_index: _trial_from_row(r)
            for r in await conn.execute(
                select(t.trials)
                .where(t.trials.c.round_id == result.round_id)
                .order_by(t.trials.c.trial_index, t.trials.c.ts)
            )
        }
        trials = list(latest.values())
        stored = {
            r.dim: Belief(r.mu, r.sigma, r.n, r.last_practised)
            for r in await conn.execute(
                select(t.dimension_state).where(
                    t.dimension_state.c.user_id == user_id,
                )
            )
        }
        # A skill measured for the first time starts from its cold-start prior (NCPT correlations).
        before = {
            d: drift(stored.get(d) or cold_start(d, stored, registry.priors), round_row.started_at)
            for d in loads
        }
        context_weight = (
            await conn.execute(
                select(func.min(t.life_context.c.weight)).where(
                    t.life_context.c.user_id == user_id,
                    t.life_context.c.period.op("@>")(round_row.started_at),
                )
            )
        ).scalar_one_or_none()
        context_weight = 1.0 if context_weight is None else float(context_weight)
        learned_b = {
            r.level_key: r.b
            for r in await conn.execute(
                select(t.item_difficulty).where(t.item_difficulty.c.game_id == game.id)
            )
        }
        item_b = {
            tr.level: learned_b[level_key(tr.level)]
            for tr in trials
            if level_key(tr.level) in learned_b
        }

        practice = registry.practice.per_round if registry.practice else None
        lag = await calibrated_lag(conn, user_id)
        outcome = score_round(
            game,
            trials,
            before,
            loads,
            context_weight=context_weight,
            device_lag_ms=lag,
            item_b=item_b,
            practice=practice,
        )
        changes = [
            DimensionChange(
                dim=d,
                mu_before=before[d].mu,
                mu_after=outcome.beliefs[d].mu,
                sigma_before=before[d].sigma,
                sigma_after=outcome.beliefs[d].sigma,
                n_after=outcome.beliefs[d].n,
                last_practised_after=outcome.beliefs[d].last_practised,
            )
            for d in loads
            if outcome.observations > 0
        ]
        flagged = outcome.quality.verdict in FLAGGED
        if flagged:
            # Rushed answers say nothing about ability, so the estimate doesn't move, but Lodestar
            # is now less sure about it (a skill with no estimate yet has nothing to widen).
            changes = [
                DimensionChange(
                    dim=d,
                    mu_before=before[d].mu,
                    mu_after=before[d].mu,
                    sigma_before=before[d].sigma,
                    sigma_after=widen(before[d], FLAGGED_WIDEN).sigma,
                    n_after=before[d].n,
                    last_practised_after=before[d].last_practised,
                )
                for d in loads
                if d in stored and stored[d].n > 0
            ]

        await append_event(
            conn,
            RoundCompleted(
                user_id=user_id, session_id=round_row.session_id, ts=now, payload=result
            ),
        )
        twin_event_id = await append_event(
            conn,
            TwinUpdated(
                user_id=user_id,
                session_id=round_row.session_id,
                ts=now,
                payload=TwinUpdatedPayload(
                    round_id=result.round_id,
                    changes=changes,
                    inputs=ScoringInputs(
                        context_weight=context_weight,
                        item_b={level_key(k): v for k, v in item_b.items()},
                        device_lag_ms=lag,
                        trust=outcome.quality.trust,
                        quality_verdict=outcome.quality.verdict,
                        practice_a=practice.a if practice else None,
                        practice_b=practice.b if practice else None,
                    ),
                ),
            ),
        )
        await _apply_changes(conn, user_id, changes, twin_event_id, now.date())
        await conn.execute(
            t.rounds.update()
            .where(t.rounds.c.round_id == result.round_id)
            .values(
                status=result.status,
                score=None if flagged else outcome.mean_score,
                ended_at=result.ended_at,
                scored_at=now,
            )
        )
        previous = (
            await conn.execute(
                select(t.rounds.c.score)
                .where(
                    t.rounds.c.user_id == user_id,
                    t.rounds.c.game_id == game.id,
                    t.rounds.c.round_id != result.round_id,
                    t.rounds.c.scored_at.is_not(None),
                )
                .order_by(t.rounds.c.scored_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if outcome.quality.trust > 0:
            observations = from_trials(game.id, trials) + iteration(
                game.id, previous, outcome.mean_score
            )
            await record_acs(
                conn, user_id, round_row.session_id, observations, result.round_id, now
            )
        if outcome.quality.trust > 0 and loads:
            primary = max(loads, key=lambda d: loads[d])
            await _learn_item_difficulty(conn, game.id, outcome, before[primary].sigma)
        await conn.execute(
            text("SELECT pg_notify(:c, :u)"), {"c": NOTIFY_CHANNEL, "u": str(user_id)}
        )
    return ScoredRound(result.round_id, outcome, changes, twin_event_id)


@dataclass(frozen=True)
class ContestResult:
    round_id: UUID
    game_id: str
    changes: list[DimensionChange]
    new: bool  # False when this round was already contested, or never counted
    counted: bool


async def contest_round(
    engine: AsyncEngine,
    user_id: UUID,
    session_id: UUID | None,
    registry: Registry,
    said: str,
    *,
    now: datetime | None = None,
) -> ContestResult | None:
    """The user says their latest round wasn't a fair reading of them. In one transaction: the
    range of each skill it touched gets wider (the estimate stays), the event log says why, and
    speaking up counts toward the AI Collaboration Score, once per round. None without a round."""
    now = now or datetime.now(UTC)
    async with engine.begin() as conn:
        await lock_user(conn, user_id)
        await user_scope(conn, user_id)
        row = (
            await conn.execute(
                select(t.rounds)
                .where(t.rounds.c.user_id == user_id, t.rounds.c.status == "completed")
                .order_by(t.rounds.c.started_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.score is None:  # rushed: it never counted, so there is nothing to soften
            return ContestResult(row.round_id, row.game_id, [], False, False)
        seen = (
            await conn.execute(
                select(func.count())
                .select_from(t.events)
                .where(
                    t.events.c.user_id == user_id,
                    t.events.c.type == "assessment.contested",
                    t.events.c.payload["round_id"].as_string() == str(row.round_id),
                )
            )
        ).scalar_one()
        if seen:
            return ContestResult(row.round_id, row.game_id, [], False, True)
        loads = dict(row.loadings or loading_matrix(registry).get(row.game_id, {}))
        changes = []
        for r in await conn.execute(
            select(t.dimension_state).where(
                t.dimension_state.c.user_id == user_id, t.dimension_state.c.dim.in_(loads)
            )
        ):
            belief = drift(Belief(r.mu, r.sigma, r.n, r.last_practised), now)
            changes.append(
                DimensionChange(
                    dim=r.dim,
                    mu_before=belief.mu,
                    mu_after=belief.mu,
                    sigma_before=belief.sigma,
                    sigma_after=widen(belief, CONTEST_WIDEN).sigma,
                    n_after=belief.n,
                    last_practised_after=belief.last_practised,
                )
            )
        twin_event = await append_event(
            conn,
            TwinUpdated(
                user_id=user_id,
                session_id=session_id,
                ts=now,
                payload=TwinUpdatedPayload(
                    round_id=row.round_id,
                    changes=changes,
                    inputs=ScoringInputs(
                        context_weight=1.0, trust=1.0, quality_verdict="contested"
                    ),
                ),
            ),
        )
        await _apply_changes(conn, user_id, changes, twin_event, now.date())
        await append_event(
            conn,
            AssessmentContested(
                user_id=user_id,
                session_id=session_id,
                ts=now,
                payload=ContestPayload(
                    round_id=row.round_id,
                    game_id=row.game_id,
                    dims=[c.dim for c in changes],
                    said=said[:300],
                ),
            ),
        )
        await record_acs(conn, user_id, session_id, pushback(row.game_id), row.round_id, now)
        await conn.execute(
            text("SELECT pg_notify(:c, :u)"), {"c": NOTIFY_CHANNEL, "u": str(user_id)}
        )
    return ContestResult(row.round_id, row.game_id, changes, True, True)


async def record_acs(
    conn: AsyncConnection,
    user_id: UUID,
    session_id: UUID | None,
    observations: Sequence[Observation],
    round_id: UUID | None,
    now: datetime,
) -> None:
    """ACS observations: a typed row each, plus an acs.observed event (docs/plan/11)."""
    for obs in observations:
        await conn.execute(
            t.acs_observations.insert().values(
                user_id=user_id,
                component=obs.component,
                success=obs.success,
                source=obs.source,
                round_id=round_id,
                ts=now,
            )
        )
        await append_event(
            conn,
            AcsObserved(
                user_id=user_id,
                session_id=session_id,
                ts=now,
                payload=AcsEvent(
                    component=obs.component,
                    success=obs.success,
                    source=obs.source,
                    round_id=round_id,
                    ts=now,
                ),
            ),
        )


async def acs_counts(conn: AsyncConnection, user_id: UUID) -> dict[str, tuple[int, int]]:
    rows = await conn.execute(
        select(
            t.acs_observations.c.component,
            func.count().filter(t.acs_observations.c.success.is_(True)),
            func.count(),
        )
        .where(t.acs_observations.c.user_id == user_id)
        .group_by(t.acs_observations.c.component)
    )
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


async def _apply_changes(
    conn: AsyncConnection,
    user_id: UUID,
    changes: Sequence[DimensionChange],
    event_id: UUID,
    day: date,
) -> None:
    for c in changes:
        state = {
            "mu": c.mu_after,
            "sigma": c.sigma_after,
            "n": c.n_after,
            "last_practised": c.last_practised_after,
            "last_event_id": event_id,
            "updated_at": func.now(),
        }
        await conn.execute(
            pg_insert(t.dimension_state)
            .values(user_id=user_id, dim=c.dim, **state)
            .on_conflict_do_update(index_elements=["user_id", "dim"], set_=state)
        )
        hist = {"mu": c.mu_after, "sigma": c.sigma_after, "n": c.n_after}
        await conn.execute(
            pg_insert(t.history)
            .values(user_id=user_id, day=day, dim=c.dim, **hist)
            .on_conflict_do_update(index_elements=["user_id", "day", "dim"], set_=hist)
        )


async def _learn_item_difficulty(
    conn: AsyncConnection, game_id: str, outcome: RoundOutcome, learner_sigma: float
) -> None:
    by_level: dict[float, list[tuple[float, float, float]]] = {}
    for item in outcome.items:
        by_level.setdefault(item.level, []).append((item.b, item.score, item.predicted))
    for level, obs in by_level.items():
        b = obs[0][0]
        for _, score, predicted in obs:
            b = update_item_difficulty(b, score, predicted, learner_sigma)
        if b == obs[0][0]:
            continue
        await conn.execute(
            pg_insert(t.item_difficulty)
            .values(game_id=game_id, level_key=level_key(level), b=b, n=len(obs))
            .on_conflict_do_update(
                index_elements=["game_id", "level_key"],
                set_={"b": b, "n": t.item_difficulty.c.n + len(obs), "updated_at": func.now()},
            )
        )


# Rebuild ----------------------------------------------------------------------------------


async def rebuild_twin(engine: AsyncEngine, user_id: UUID) -> int:
    """Delete the user's projections and replay twin.snapshot and twin.updated events in order.
    Returns the number of events applied."""
    async with engine.begin() as conn:
        await lock_user(conn, user_id)
        await conn.execute(t.dimension_state.delete().where(t.dimension_state.c.user_id == user_id))
        await conn.execute(t.history.delete().where(t.history.c.user_id == user_id))
        rows = await conn.execute(
            select(t.events)
            .where(
                t.events.c.user_id == user_id,
                t.events.c.type.in_(["twin.snapshot", "twin.updated"]),
            )
            .order_by(t.events.c.ts, t.events.c.event_id)
        )
        state: dict[str, dict[str, Any]] = {}
        history: dict[tuple[date, str], HistoryRow] = {}
        applied = 0
        for row in rows:
            event = parse_event(
                {
                    "event_id": row.event_id,
                    "user_id": row.user_id,
                    "session_id": row.session_id,
                    "ts": row.ts,
                    "type": row.type,
                    "schema_version": row.schema_version,
                    "payload": row.payload,
                }
            )
            applied += 1
            if event.type == "twin.snapshot":
                state = {
                    d.dim: {
                        "mu": d.mu,
                        "sigma": d.sigma,
                        "n": d.n,
                        "last_practised": d.last_practised,
                        "last_event_id": row.event_id,
                    }
                    for d in event.payload.dims
                }
                history = {(h.day, h.dim): h for h in event.payload.history}
            elif event.type == "twin.updated":
                day = row.ts.astimezone(UTC).date()
                for c in event.payload.changes:
                    state[c.dim] = {
                        "mu": c.mu_after,
                        "sigma": c.sigma_after,
                        "n": c.n_after,
                        "last_practised": c.last_practised_after,
                        "last_event_id": row.event_id,
                    }
                    history[(day, c.dim)] = HistoryRow(
                        day=day, dim=c.dim, mu=c.mu_after, sigma=c.sigma_after, n=c.n_after
                    )
        if state:
            await conn.execute(
                t.dimension_state.insert(),
                [{"user_id": user_id, "dim": d, **v} for d, v in state.items()],
            )
        if history:
            await conn.execute(
                t.history.insert(),
                [{"user_id": user_id, **h.model_dump()} for h in history.values()],
            )
    return applied


# Reads ------------------------------------------------------------------------------------


async def read_twin(
    conn: AsyncConnection, user_id: UUID, *, now: datetime | None = None, norms: Norms | None = None
) -> TwinView:
    now = now or datetime.now(UTC)
    norms = norms or Norms()
    dims = []
    for r in await conn.execute(
        select(t.dimension_state)
        .where(t.dimension_state.c.user_id == user_id)
        .order_by(t.dimension_state.c.dim)
    ):
        belief = drift(Belief(r.mu, r.sigma, r.n, r.last_practised), now)
        pct = norms.percentile(r.dim, belief)
        dims.append(
            DimensionView(
                dim=r.dim,
                mu=belief.mu,
                sigma=belief.sigma,
                n=belief.n,
                last_practised=belief.last_practised,
                percent=pct.value,
                percent_low=pct.low,
                percent_high=pct.high,
                norms=pct.source,
                still_learning=belief.sigma > STILL_LEARNING_SIGMA,
            )
        )
    history = [
        HistoryRow(day=r.day, dim=r.dim, mu=r.mu, sigma=r.sigma, n=r.n)
        for r in await conn.execute(
            select(t.history)
            .where(t.history.c.user_id == user_id)
            .order_by(t.history.c.day, t.history.c.dim)
        )
    ]
    curves = []
    for h in history:
        pr = norms.percentile(h.dim, Belief(h.mu, h.sigma))
        curves.append(
            CurvePoint(day=h.day, dim=h.dim, percent=pr.value, low=pr.low, high=pr.high, n=h.n)
        )
    return TwinView(user_id=user_id, as_of=now, dims=dims, history=history, curves=curves)
