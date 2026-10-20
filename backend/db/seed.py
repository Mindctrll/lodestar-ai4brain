"""`make seed`: a demo user with three weeks of practice, for building the dashboard.

Projection rows (dimension_state, history) are written directly with a simple random walk. They are
demo data only: once the scoring engine exists, `make rebuild-twin` recomputes them from the
events written here.
"""

import argparse
import random
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from psycopg.types.range import Range
from sqlalchemy import Connection, insert, select

from backend.db import tables as t
from backend.db.engine import get_engine
from backend.registry.loader import load_registry

DEMO_NAME = "Amira"
DAYS = 21
SEED = 7


def _ts(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def seed_demo_user(conn: Connection, today: date | None = None) -> UUID:
    rng = random.Random(SEED)
    today = today or datetime.now(UTC).date()
    registry = load_registry()
    p1_games = [g for g in registry.games if g.phase == "P1"]
    tracked = [d.id for d in registry.dimensions if d.badge != "experimental"]

    user_id: UUID = conn.execute(
        insert(t.users)
        .values(display_name=DEMO_NAME, persona="zitouna", age_confirmed=True)
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
                notice_version="1",
                changed_at=_ts(start, 20),
            )
        )
    conn.execute(
        insert(t.goals).values(
            user_id=user_id,
            dim="working_memory",
            kind="range",
            target=0.1,
            due=today + timedelta(days=13),
        )
    )
    conn.execute(
        insert(t.life_context).values(
            user_id=user_id,
            label="exam week",
            period=Range(_ts(today + timedelta(days=3), 0), _ts(today + timedelta(days=14), 0)),
            weight=0.5,
        )
    )

    # Belief per skill: starts wide, sharpens with practice.
    belief = {d: {"mu": 0.0, "sigma": 1.5, "n": 0} for d in tracked}
    for offset in range(DAYS):
        day = start + timedelta(days=offset)
        if rng.random() < 0.35:  # not every day
            continue
        hour = rng.choice([8, 13, 20, 21, 22])
        session_id = uuid4()
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
                payload={"trigger": "ui", "persona": "zitouna"},
            )
        )
        for r, game in enumerate(rng.sample(p1_games, 3)):
            round_id = uuid4()
            level = round(rng.uniform(0.2, 0.7), 2)
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
            for i in range(10):
                correct = rng.random() < 0.78
                correct_count += correct
                trial = {
                    "trial_id": uuid4(), "user_id": user_id, "session_id": session_id,
                    "round_id": round_id, "game_id": game.id, "level": level, "trial_index": i,
                    "correct": correct, "rt_ms": round(rng.lognormvariate(6.4, 0.25), 1),
                    "stimulus": {"i": i}, "response": {"ok": correct},
                    "ts": started + timedelta(seconds=6 * i),
                }  # fmt: skip
                conn.execute(insert(t.trials).values(**trial))
                conn.execute(
                    insert(t.events).values(
                        user_id=user_id,
                        session_id=session_id,
                        ts=trial["ts"],
                        type="trial.recorded",
                        payload={
                            k: str(v) if isinstance(v, (UUID, datetime)) else v
                            for k, v in trial.items()
                            if k != "user_id"
                        },
                    )
                )
            score = correct_count / 10
            conn.execute(
                t.rounds.update().where(t.rounds.c.round_id == round_id).values(score=score)
            )
            for dim, loading in game.dims.items():
                if dim not in belief:
                    continue
                b = belief[dim]
                b["mu"] += loading * rng.uniform(-0.05, 0.12)
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
                payload={"reason": "budget", "rounds": 3, "minutes": 12},
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
        for _ in range(12):
            conn.execute(
                insert(t.acs_observations).values(
                    user_id=user_id,
                    component=component,
                    success=rng.random() < rate,
                    source="seed",
                )
            )
    return user_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete earlier demo users first")
    args = parser.parse_args()
    with get_engine().begin() as conn:
        if args.reset:
            conn.execute(t.users.delete().where(t.users.c.display_name == DEMO_NAME))
        elif conn.execute(
            select(t.users.c.user_id).where(t.users.c.display_name == DEMO_NAME)
        ).first():
            print(f"Demo user {DEMO_NAME} already exists; use --reset to recreate.")
            return
        user_id = seed_demo_user(conn)
    print(f"Seeded demo user {DEMO_NAME}: {user_id}")


if __name__ == "__main__":
    main()
