"""`make seed`: a demo user with four months of practice, goals, life notes, experiments and
the agent's decisions, for building and showing the dashboard. Their memory notes are written by
`backend.db.seed_memory`, which runs inside the backend container. The "Demo" button in the app
does the same through `POST /demo` (backend/api/demo.py).

Projection rows (dimension_state, history) are written directly with a simple random walk. They are
demo data only: once the scoring engine exists, `make rebuild-twin` recomputes them from the
events written here.
"""

import argparse
import random
import secrets
import zlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from psycopg.types.range import Range
from sqlalchemy import Connection, func, insert, select

from backend.agent.experiments import compare, design
from backend.db import tables as t
from backend.db.engine import get_engine
from backend.db.twin_store import hash_token
from backend.registry.loader import load_registry
from backend.registry.models import Registry

DEMO_NAME = "Alex"
DAYS = 120
SEED = 7
# How fast each skill grows per practised round, before noise: some climb, some hold still.
GROWTH = {
    "working_memory": 0.035,
    "processing_speed": 0.03,
    "inhibition": 0.03,
    "cognitive_flexibility": 0.03,
    "reasoning": 0.02,
    "short_term_memory": 0.025,
    "selective_attention": 0.015,
}
DEFAULT_GROWTH = 0.025
NOISE = 0.1
# Where each skill starts. Alex's reasoning is far ahead of their selective attention, so the
# demo shows a split profile with a track for each side.
START = {"reasoning": 1.9, "spatial_thinking": 0.9, "selective_attention": -2.4}
DEFAULT_START = -0.4
# A plateau: played every other session lately, and it barely moves.
PLATEAU_DIM = "sustained_attention"
PLATEAU_GAME = "night_guard"
PLATEAU_DAYS = 46
# Every other skill keeps moving lately, so only the plateau reads as stuck.
LATE_GROWTH = 3.0
# (label, first day relative to today, length in days): short nights and busy weeks cost a little.
LIFE = [
    ("short nights", -98, 4),
    ("new job", -84, 10),
    ("short nights", -40, 3),
    ("holiday", -26, 5),
    ("cold", -18, 3),
    ("busy at work", -12, 4),
    ("exam week", 3, 11),
]
HARD_TIMES = {"short nights", "busy at work", "cold", "new job"}


def _ts(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def tracked_dims(registry: Registry) -> list[str]:
    """Every non-experimental skill, plus any experimental one a seeded (P1) game measures."""
    seeded = {d for g in registry.games if g.phase == "P1" for d in g.dims}
    return [d.id for d in registry.dimensions if d.badge != "experimental" or d.id in seeded]


def seed_demo_user(conn: Connection, today: date | None = None) -> UUID:
    rng = random.Random(SEED)
    today = today or datetime.now(UTC).date()
    registry = load_registry()
    p1_games = [g for g in registry.games if g.phase == "P1"]
    p2_games = [g for g in registry.games if g.phase == "P2"]
    tracked = tracked_dims(registry)

    user_id: UUID = conn.execute(
        insert(t.users)
        .values(display_name=DEMO_NAME, persona="willow", age_confirmed=True)
        .returning(t.users.c.user_id)
    ).scalar_one()
    start = today - timedelta(days=DAYS)
    for switch, granted in [
        ("core", True),
        ("cloud_ai", False),
        ("microphone", True),
        ("camera", False),
        ("voice_tone", False),
        ("deliberate_mistakes", True),
        ("research_export", False),
    ]:
        conn.execute(
            insert(t.consent).values(
                user_id=user_id,
                switch=switch,
                granted=granted,
                notice_version=registry.consent.version,
                changed_at=_ts(start, 20),
            )
        )
    for dim, target, due in [
        ("working_memory", 15, 13),  # the 80% range within ±15 points (UW11)
        ("processing_speed", 12, 20),
        ("inhibition", 18, 30),
        ("reasoning", 16, 45),
        ("sustained_attention", 20, 60),
    ]:
        conn.execute(
            insert(t.goals).values(
                user_id=user_id, dim=dim, kind="range", target=target,
                due=today + timedelta(days=due),
            )
        )  # fmt: skip
    hard_days: set[date] = set()
    for label, begin, days in LIFE:
        day = today + timedelta(days=begin)
        if label in HARD_TIMES:
            hard_days.update(day + timedelta(days=i) for i in range(days))
        conn.execute(
            insert(t.life_context).values(
                user_id=user_id, label=label,
                period=Range(_ts(day, 0), _ts(day + timedelta(days=days), 0)), weight=0.5,
            )
        )  # fmt: skip

    # Belief per skill: starts wide, sharpens with practice.
    belief = {d: {"mu": START.get(d, DEFAULT_START), "sigma": 1.5, "n": 0} for d in tracked}
    session_ids: list[tuple[UUID, datetime]] = []
    for offset in range(DAYS):
        day = start + timedelta(days=offset)
        holiday = -26 <= (day - today).days < -21
        skip = 0.85 if holiday else 0.25
        if offset < DAYS - 9 and rng.random() < skip:  # not every day; a streak lately
            continue
        hour = rng.choice([8, 9, 13, 18, 20, 21, 22])
        session_id = uuid4()
        session_ids.append((session_id, _ts(day, hour)))
        conn.execute(
            insert(t.sessions).values(
                session_id=session_id,
                user_id=user_id,
                trigger="ui",
                status="ended",
                started_at=_ts(day, hour),
                ended_at=_ts(day, hour, 12),
            )
        )
        conn.execute(
            insert(t.events).values(
                user_id=user_id,
                session_id=session_id,
                ts=_ts(day, hour),
                type="session.started",
                payload={"trigger": "ui", "persona": "willow"},
            )
        )
        # The last two weeks have long sessions that slow down after about 13 minutes, so the
        # fatigue point (docs/plan/10) has something to find.
        recent = offset >= DAYS - 14
        # Later on, the wider set of games joins the first sixteen.
        pool = p1_games if offset < DAYS // 3 else p1_games + p2_games
        played = rng.sample(pool, 5 if recent else rng.choice([3, 3, 4, 4]))
        stuck = offset >= DAYS - PLATEAU_DAYS
        if stuck and len(session_ids) % 2 == 0:
            guard = registry.game(PLATEAU_GAME)
            played = [guard, *[g for g in played if g.id != PLATEAU_GAME]]
        # Evenings go a little better (the experiments find it), hard days a little worse.
        base = 0.72 + 0.12 * offset / DAYS + (0.05 if hour >= 18 else 0.0)
        base -= 0.08 if day in hard_days else 0.0
        for r, game in enumerate(played):
            round_id = uuid4()
            level = round(min(0.95, rng.uniform(0.2, 0.5) + 0.35 * offset / DAYS), 2)
            started = _ts(day, hour, 1 + r * 4)
            correct_count = 0
            conn.execute(
                insert(t.rounds).values(
                    round_id=round_id,
                    user_id=user_id,
                    session_id=session_id,
                    game_id=game.id,
                    level=level,
                    status="completed",
                    started_at=started,
                    ended_at=started + timedelta(minutes=2),
                )
            )
            tired = recent and r >= 3
            trials, events = [], []
            for i in range(10):
                correct = rng.random() < (base - 0.08 if tired else base)
                correct_count += correct
                slow = 1.45 if tired else 1.0
                # About one answer in seven gets a "How sure?" reading, a little over-confident.
                sure = rng.choice([0.7, 0.8, 0.8, 0.9, 0.9, 1.0]) if i % 7 == 3 else None
                trial = {
                    "trial_id": uuid4(), "user_id": user_id, "session_id": session_id,
                    "round_id": round_id, "game_id": game.id, "level": level, "trial_index": i,
                    "correct": correct, "rt_ms": round(rng.lognormvariate(6.4, 0.25) * slow, 1),
                    "confidence": sure, "stimulus": {"i": i}, "response": {"ok": correct},
                    "ts": started + timedelta(seconds=6 * i),
                }  # fmt: skip
                trials.append(trial)
                events.append(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "ts": trial["ts"],
                        "type": "trial.recorded",
                        "payload": {
                            k: str(v) if isinstance(v, (UUID, datetime)) else v
                            for k, v in trial.items()
                            if k != "user_id"
                        },
                    }
                )
            conn.execute(insert(t.trials), trials)
            conn.execute(insert(t.events), events)
            score = correct_count / 10
            conn.execute(
                t.rounds.update()
                .where(t.rounds.c.round_id == round_id)
                .values(score=score, scored_at=started + timedelta(minutes=2))
            )
            for dim, loading in game.dims.items():
                if dim not in belief:
                    continue
                b = belief[dim]
                if dim == PLATEAU_DIM and stuck:
                    b["mu"] += loading * rng.uniform(-0.015, 0.015)
                else:
                    b["mu"] += loading * (
                        GROWTH.get(dim, DEFAULT_GROWTH) + rng.uniform(-NOISE, NOISE)
                    )
                b["sigma"] = max(0.35, b["sigma"] * (0.93 if loading == 1.0 else 0.98))
                b["n"] += 10
        for dim, b in belief.items():
            if b["n"]:
                conn.execute(
                    insert(t.history).values(
                        user_id=user_id, day=day, dim=dim, mu=b["mu"], sigma=b["sigma"], n=b["n"]
                    )
                )
        conn.execute(
            insert(t.events).values(
                user_id=user_id,
                session_id=session_id,
                ts=_ts(day, hour, 12),
                type="session.ended",
                payload={"reason": "budget", "rounds": len(played), "minutes": 4 * len(played)},
            )
        )

    last = _ts(today, 0)
    for dim, b in belief.items():
        conn.execute(
            insert(t.dimension_state).values(
                user_id=user_id,
                dim=dim,
                mu=b["mu"],
                sigma=b["sigma"],
                n=b["n"],
                last_practised=last if b["n"] else None,
            )
        )
    for component, rate in {"V": 0.7, "A": 0.6, "I": 0.5, "C": 0.4, "R": 0.8}.items():
        for _ in range(60):
            conn.execute(
                insert(t.acs_observations).values(
                    user_id=user_id,
                    component=component,
                    success=rng.random() < rate,
                    source="seed",
                )
            )
    _seed_experiments(conn, user_id, rng, today)
    names = {d.id: d.name.lower() for d in registry.dimensions}
    _seed_decisions(conn, user_id, rng, session_ids[-30:], belief, names)
    return user_id


def _seed_experiments(conn: Connection, user_id: UUID, rng: random.Random, today: date) -> None:
    """Four finished time-of-day experiments: two where the evening won, two too close to call.
    None is left running, so the demo can start a new one."""
    for hypothesis, games, dim, (m_lo, m_hi), (e_lo, e_hi), ago in [
        ("I hold back faster in the evening", ["hold_it", "brake"], "inhibition",
         (0.55, 0.68), (0.68, 0.82), 60),
        ("My attention lasts longer in the morning", ["night_guard", "look_here"],
         "sustained_attention", (0.6, 0.72), (0.6, 0.73), 33),
        ("I react faster in the evening than in the morning", ["quick_draw", "echo"],
         "processing_speed", (0.55, 0.7), (0.7, 0.85), 9),
        ("My memory is sharper in the morning", ["echo", "seen_it"], "working_memory",
         (0.6, 0.75), (0.58, 0.74), 2),
    ]:  # fmt: skip
        morning = [round(rng.uniform(m_lo, m_hi), 3) for _ in range(3)]
        evening = [round(rng.uniform(e_lo, e_hi), 3) for _ in range(3)]
        c = compare(morning, evening)
        sessions = [
            {"session_id": str(uuid4()), "condition": cond, "score": score}
            for cond, scores in (("morning", morning), ("evening", evening))
            for score in scores
        ]
        done = _ts(today - timedelta(days=ago), 21)
        conn.execute(
            insert(t.experiments).values(
                user_id=user_id, hypothesis=hypothesis, design=design(games, dim),
                status="completed" if c.verdict != "inconclusive" else "inconclusive",
                result={
                    "sessions": sessions, "verdict": c.verdict,
                    "p_evening_better": round(c.p_evening_better, 3),
                    "difference": round(c.difference, 4),
                    "interval": [round(c.low, 4), round(c.high, 4)],
                    "wins": c.wins, "pairs": c.pairs,
                },
                created_at=done - timedelta(days=10), updated_at=done,
            )
        )  # fmt: skip


def _seed_decisions(
    conn: Connection, user_id: UUID, rng: random.Random, sessions: list[tuple[UUID, datetime]],
    belief: dict[str, dict[str, float]], names: dict[str, str],
) -> None:  # fmt: skip
    """The agent's "which skill next" choice for recent sessions, with each score's parts."""
    for session_id, at in sessions:
        options = rng.sample(sorted(d for d, b in belief.items() if b["n"]), 3)
        candidates = []
        for dim in options:
            parts = {
                "uncertainty": round(belief[dim]["sigma"] / 1.5, 3),
                "staleness": round(rng.uniform(0, 1), 3),
                "goal_weight": 1.0 if dim in ("working_memory", "processing_speed") else 0.0,
                "bandit_gain": round(rng.uniform(0, 0.4), 3),
                "repetition": float(rng.random() < 0.2),
            }
            score = parts["uncertainty"] + 0.6 * parts["staleness"] + 0.5 * parts["goal_weight"]
            candidates.append({"option": dim, "score": round(score, 4), "breakdown": parts})
        candidates.sort(key=lambda c: -float(c["score"]))  # type: ignore[arg-type]
        chosen = str(candidates[0]["option"])
        name = names[chosen]
        conn.execute(
            insert(t.decisions).values(
                decision_id=uuid4(), session_id=session_id, user_id=user_id, node="plan_next",
                question="Which skill and game next?", candidates=candidates, chosen=chosen,
                reason=f"I'm least sure about your {name}, so a round there teaches me the most.",
                ts=at,
            )
        )  # fmt: skip


def issue_token(conn: Connection, user_id: UUID) -> str:
    """A bearer token for the demo user, so the browser can sign in as them."""
    token = secrets.token_urlsafe(32)
    conn.execute(insert(t.user_tokens).values(token_hash=hash_token(token), user_id=user_id))
    return token


def demo_sign_in(conn: Connection) -> tuple[UUID, str, bool]:
    """The demo user and a fresh sign-in token for them, seeding them first if they're missing.
    Returns whether they were just created. Safe when two tabs ask at once."""
    conn.execute(select(func.pg_advisory_xact_lock(zlib.crc32(b"lodestar.demo"))))
    existing = conn.execute(
        select(t.users.c.user_id).where(t.users.c.display_name == DEMO_NAME)
    ).scalar_one_or_none()
    user_id = existing or seed_demo_user(conn)
    return user_id, issue_token(conn, user_id), existing is None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete earlier demo users first")
    parser.add_argument(
        "--token", action="store_true", help="print a sign-in token and link for the demo user"
    )
    args = parser.parse_args()
    with get_engine().begin() as conn:
        existing = conn.execute(
            select(t.users.c.user_id).where(t.users.c.display_name == DEMO_NAME)
        ).scalar_one_or_none()
        if args.reset:
            conn.execute(t.users.delete().where(t.users.c.display_name == DEMO_NAME))
            existing = None
        if existing is None:
            user_id = seed_demo_user(conn)
            print(f"Seeded demo user {DEMO_NAME}: {user_id}")
        else:
            user_id = existing
            print(f"Demo user {DEMO_NAME} already exists ({user_id}); --reset recreates it.")
        if args.token:
            token = issue_token(conn, user_id)
            print(f"TOKEN={token}")
            print(f"Sign in as {DEMO_NAME}: http://localhost:5173/?signin={token}")
            print(f"Or in a terminal: bin/lodestar login --code {token}")


if __name__ == "__main__":
    main()
