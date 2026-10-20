from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from psycopg.errors import InsufficientPrivilege, RestrictViolation, UniqueViolation
from psycopg.types.range import Range
from sqlalchemy import Connection, Engine, MetaData, Table, func, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError

from backend.db import tables as t
from tests.backend.db.conftest import BASE_URL, alembic_config, recreate_database

NOW = datetime.now(UTC)


def _user(conn: Connection) -> UUID:
    user_id: UUID = conn.execute(
        insert(t.users).values(display_name="Test").returning(t.users.c.user_id)
    ).scalar_one()
    return user_id


def _round(conn: Connection, user_id: UUID, session_id: UUID) -> UUID:
    round_id = uuid4()
    conn.execute(
        insert(t.rounds).values(
            round_id=round_id, user_id=user_id, session_id=session_id, game_id="echo", level=0.4
        )
    )
    return round_id


def test_tables_match_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    for table in t.metadata.tables.values():
        reflected = {c["name"]: c for c in inspector.get_columns(table.name, schema=table.schema)}
        assert set(reflected) == {c.name for c in table.columns}, table.fullname
        for column in table.columns:
            assert reflected[column.name]["nullable"] == column.nullable, (
                f"{table.fullname}.{column.name}"
            )


def test_every_table_accepts_and_returns_a_row(conn: Connection) -> None:
    user_id = _user(conn)
    session_id = conn.execute(
        insert(t.sessions).values(user_id=user_id, trigger="ui").returning(t.sessions.c.session_id)
    ).scalar_one()
    round_id = _round(conn, user_id, session_id)
    item_id = conn.execute(
        insert(t.content_pool)
        .values(game_id="souk_rush", level=0.5, content={"orders": []}, validator_report={})
        .returning(t.content_pool.c.item_id)
    ).scalar_one()

    rows: dict[Table, dict[str, object]] = {
        t.consent: {"user_id": user_id, "switch": "core", "granted": True, "notice_version": "1"},
        t.goals: {"user_id": user_id, "dim": "working_memory", "kind": "range", "target": 0.1,
                  "due": date(2026, 11, 7)},
        t.deletion_receipts: {"user_hash": "abc", "counts": {"events": 3}},
        t.llm_credentials: {"user_id": user_id, "provider": "gemini", "key_ciphertext": b"x",
                            "nonce": b"n", "master_key_version": 1, "key_last4": "a91F"},
        t.llm_selection: {"user_id": user_id, "mode": "local", "provider": "ollama",
                          "model": "qwen3.5:4b"},
        t.events: {"user_id": user_id, "session_id": session_id, "type": "session.started",
                   "payload": {"trigger": "ui", "persona": "zitouna"}},
        t.trials: {"trial_id": uuid4(), "user_id": user_id, "session_id": session_id,
                   "round_id": round_id, "game_id": "echo", "level": 0.4, "trial_index": 0,
                   "correct": True, "rt_ms": 420.0, "stimulus": {"letter": "K"}, "ts": NOW},
        t.dimension_state: {"user_id": user_id, "dim": "working_memory", "mu": 0.1, "sigma": 1.2},
        t.history: {"user_id": user_id, "day": date(2026, 10, 21), "dim": "working_memory",
                    "mu": 0.1, "sigma": 1.2, "n": 4},
        t.item_difficulty: {"game_id": "echo", "level_key": "n=2", "b": 0.3},
        t.acs_observations: {"user_id": user_id, "component": "V", "success": True,
                             "source": "spot_the_mistake"},
        t.life_context: {"user_id": user_id, "label": "exam week",
                         "period": Range(NOW, NOW + timedelta(days=7))},
        t.decisions: {"decision_id": uuid4(), "session_id": session_id, "user_id": user_id,
                      "node": "plan_next", "question": "Which skill next?", "candidates": [],
                      "chosen": "working_memory", "reason": "Least certain skill"},
        t.traces: {"session_id": session_id, "seq": 1, "user_id": user_id, "node": "ingest",
                   "event": "done", "ms": 3.5},
        t.experiments: {"user_id": user_id, "hypothesis": "Evening is better",
                        "design": {"sessions": 6}},
        t.content_served: {"user_id": user_id, "item_id": item_id},
        t.ml_models: {"name": "growth_forecast", "version": "1", "metrics": {"coverage": 0.79},
                      "artefact_path": "models/growth/1.txt", "trained_at": NOW},
    }  # fmt: skip
    for table, values in rows.items():
        conn.execute(insert(table).values(**values))
        assert conn.execute(select(func.count()).select_from(table)).scalar_one() >= 1, table


def test_event_log_is_append_only(engine: Engine) -> None:
    with engine.connect() as conn:
        user_id = _user(conn)
        conn.execute(insert(t.events).values(user_id=user_id, type="x", payload={}))
        conn.commit()
        with pytest.raises(DBAPIError) as excinfo:
            conn.execute(
                text("UPDATE twin.events SET type = 'y' WHERE user_id = :u"), {"u": user_id}
            )
        assert isinstance(excinfo.value.orig, RestrictViolation)
        conn.rollback()
        with pytest.raises(DBAPIError) as excinfo:
            conn.execute(text("TRUNCATE twin.events"))
        assert isinstance(excinfo.value.orig, RestrictViolation)
        conn.rollback()
        conn.execute(t.users.delete().where(t.users.c.user_id == user_id))
        conn.commit()


def test_app_role_cannot_rewrite_events(conn: Connection) -> None:
    user_id = _user(conn)
    conn.execute(insert(t.events).values(user_id=user_id, type="x", payload={}))
    conn.execute(text("SET LOCAL ROLE najma_app"))
    conn.execute(insert(t.events).values(user_id=user_id, type="y", payload={}))
    with pytest.raises(DBAPIError) as excinfo, conn.begin_nested():
        conn.execute(text("DELETE FROM twin.events WHERE user_id = :u"), {"u": user_id})
    assert isinstance(excinfo.value.orig, InsufficientPrivilege)


def test_events_land_in_monthly_partition(conn: Connection) -> None:
    user_id = _user(conn)
    partition = conn.execute(
        text(
            "INSERT INTO twin.events (user_id, type, payload) VALUES (:u, 'x', '{}') "
            "RETURNING tableoid::regclass::text"
        ),
        {"u": user_id},
    ).scalar_one()
    assert partition == f"twin.events_{NOW:%Y_%m}"


def test_deleting_a_user_cascades_everywhere(conn: Connection) -> None:
    user_id = _user(conn)
    session_id = uuid4()
    round_id = _round(conn, user_id, session_id)
    conn.execute(insert(t.events).values(user_id=user_id, type="x", payload={}))
    conn.execute(
        insert(t.trials).values(
            trial_id=uuid4(),
            user_id=user_id,
            session_id=session_id,
            round_id=round_id,
            game_id="echo",
            level=0.4,
            trial_index=0,
            stimulus={},
            ts=NOW,
        )
    )
    conn.execute(insert(t.dimension_state).values(user_id=user_id, dim="d", mu=0, sigma=1))
    conn.execute(t.users.delete().where(t.users.c.user_id == user_id))
    for table in t.USER_TABLES:
        count = conn.execute(
            select(func.count()).select_from(table).where(table.c.user_id == user_id)
        ).scalar_one()
        assert count == 0, table.fullname


def test_only_one_active_model_per_name(conn: Connection) -> None:
    row = {"name": "m", "metrics": {}, "artefact_path": "p", "trained_at": NOW, "active": True}
    conn.execute(insert(t.ml_models).values(version="1", **row))
    with pytest.raises(DBAPIError) as excinfo, conn.begin_nested():
        conn.execute(insert(t.ml_models).values(version="2", **row))
    assert isinstance(excinfo.value.orig, UniqueViolation)


def test_checkpoint_tables_exist(engine: Engine) -> None:
    names = set(inspect(engine).get_table_names(schema="public"))
    assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} <= names


def test_migrations_downgrade_and_upgrade_cleanly() -> None:
    url = BASE_URL.rsplit("/", 1)[0] + "/najma_test_migrations"
    recreate_database(url)
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    from sqlalchemy import create_engine

    from backend.db.engine import sync_url

    eng = create_engine(sync_url(url))
    try:
        reflected = MetaData()
        reflected.reflect(eng, schema="twin")
        assert "twin.events" in reflected.tables
    finally:
        eng.dispose()
