"""Trace sequence numbers from a sequence, so parallel nodes never collide.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SEQUENCE agent.trace_seq AS bigint;
        ALTER TABLE agent.traces ALTER COLUMN seq TYPE bigint;
        ALTER TABLE agent.traces ALTER COLUMN seq SET DEFAULT nextval('agent.trace_seq');
        ALTER SEQUENCE agent.trace_seq OWNED BY agent.traces.seq;
        GRANT USAGE ON SEQUENCE agent.trace_seq TO lodestar_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent.traces ALTER COLUMN seq DROP DEFAULT;
        DROP SEQUENCE agent.trace_seq;
        ALTER TABLE agent.traces ALTER COLUMN seq TYPE integer;
        """
    )
