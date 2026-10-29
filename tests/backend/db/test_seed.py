from sqlalchemy import Connection, Table, func, select

from backend.db import tables as t
from backend.db.seed import DEMO_NAME, demo_sign_in, seed_demo_user, tracked_dims
from backend.db.twin_store import hash_token
from backend.registry.loader import load_registry


def test_seed_creates_a_consistent_demo_user(conn: Connection) -> None:
    user_id = seed_demo_user(conn)

    def count(table: Table) -> int:
        query = select(func.count()).select_from(table).where(table.c.user_id == user_id)
        return int(conn.execute(query).scalar_one())

    rounds = count(t.rounds)
    assert rounds > 0
    assert count(t.trials) == rounds * 10
    assert count(t.events) == count(t.trials) + 2 * count(t.sessions)
    assert count(t.dimension_state) == len(tracked_dims(load_registry()))
    assert count(t.history) > 0
    assert count(t.consent) == 7
    assert count(t.goals) == 5
    assert count(t.experiments) == 4
    assert count(t.decisions) > 0


def test_demo_sign_in_seeds_once_and_hands_out_fresh_tokens(conn: Connection) -> None:
    conn.execute(t.users.delete().where(t.users.c.display_name == DEMO_NAME))
    first, token_a, created_a = demo_sign_in(conn)
    again, token_b, created_b = demo_sign_in(conn)
    assert (created_a, created_b) == (True, False)
    assert first == again and token_a != token_b
    owners = conn.execute(
        select(t.user_tokens.c.user_id).where(
            t.user_tokens.c.token_hash.in_([hash_token(token_a), hash_token(token_b)])
        )
    ).scalars()
    assert set(owners) == {first}
