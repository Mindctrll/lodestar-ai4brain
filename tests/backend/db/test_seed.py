from sqlalchemy import Connection, Table, func, select

from backend.db import tables as t
from backend.db.seed import seed_demo_user


def test_seed_creates_a_consistent_demo_user(conn: Connection) -> None:
    user_id = seed_demo_user(conn)

    def count(table: Table) -> int:
        query = select(func.count()).select_from(table).where(table.c.user_id == user_id)
        return int(conn.execute(query).scalar_one())

    rounds = count(t.rounds)
    assert rounds > 0 and rounds % 3 == 0
    assert count(t.trials) == rounds * 10
    assert count(t.events) == count(t.trials) + 2 * count(t.sessions)
    assert count(t.dimension_state) == 14  # every non-experimental dimension
    assert count(t.history) > 0
    assert count(t.consent) == 7
