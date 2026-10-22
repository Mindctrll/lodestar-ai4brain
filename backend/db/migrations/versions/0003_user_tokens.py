"""Bearer tokens for API access. Only a SHA-256 hash of each token is stored.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.user_tokens (
            token_hash  text PRIMARY KEY,
            user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
            created_at  timestamptz NOT NULL DEFAULT now(),
            last_used   timestamptz
        );
        CREATE INDEX user_tokens_user_idx ON app.user_tokens (user_id);
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.user_tokens TO lodestar_app;
        GRANT SELECT, DELETE ON app.user_tokens TO lodestar_jobs;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.user_tokens")
