"""Database fixtures. Tests run against a throwaway database in the compose Postgres
(`make up`). Set NAJMA_REQUIRE_DB=1 (as CI does) to fail instead of skipping when it's down."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import make_url

from backend.db.engine import libpq_url, sync_url

BASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://najma:najma@localhost:5442/najma_test")


def _admin_conninfo(url: str) -> str:
    return libpq_url(make_url(url).set(database="postgres").render_as_string(hide_password=False))


def recreate_database(url: str) -> None:
    name = make_url(url).database
    try:
        with psycopg.connect(_admin_conninfo(url), autocommit=True, connect_timeout=3) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        if os.environ.get("NAJMA_REQUIRE_DB"):
            raise
        pytest.skip(f"Postgres not reachable ({exc.__class__.__name__}); run `make up`")


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def db_url() -> str:
    recreate_database(BASE_URL)
    command.upgrade(alembic_config(BASE_URL), "head")
    return BASE_URL


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_engine(sync_url(db_url))
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A connection whose work is rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()
