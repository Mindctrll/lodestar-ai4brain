"""LangGraph checkpoint tables (docs/plan/03, Persistence).

`PostgresSaver.setup()` keeps its own migration log (`checkpoint_migrations`), so re-running it
after a langgraph upgrade only applies what's new. It needs an autocommit connection because some
of its steps build indexes concurrently.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver

from backend.db.engine import libpq_url

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _conninfo() -> str:
    url = op.get_bind().engine.url.render_as_string(hide_password=False)
    return libpq_url(url)


def upgrade() -> None:
    with PostgresSaver.from_conn_string(_conninfo()) as saver:
        saver.setup()


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs, checkpoints, "
        "checkpoint_migrations"
    )
