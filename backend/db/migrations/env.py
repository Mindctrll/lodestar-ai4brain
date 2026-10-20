"""Alembic environment. Migrations are hand-written SQL; `backend/db/tables.py` mirrors them for
queries, and tests/backend/db/test_schema.py checks the two agree."""

from alembic import context
from sqlalchemy import create_engine, pool

from backend.db.engine import sync_url

config = context.config


def run_migrations() -> None:
    url = config.get_main_option("sqlalchemy.url") or sync_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a database.")
run_migrations()
