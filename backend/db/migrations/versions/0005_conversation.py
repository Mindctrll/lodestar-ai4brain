"""Conversation tools (WP2.11): the user's time zone, so "today" means their day, and paused
skill suggestions ("stop suggesting memory this week", UW3).

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.users ADD COLUMN timezone text NOT NULL DEFAULT 'Africa/Tunis';

        CREATE TABLE app.skill_pauses (
            pause_id    uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
            dim         text NOT NULL,
            until       timestamptz NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX skill_pauses_user_idx ON app.skill_pauses (user_id, until);
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.skill_pauses TO najma_app;
        GRANT SELECT, INSERT, DELETE ON app.skill_pauses TO najma_jobs;
        GRANT SELECT ON app.skill_pauses TO najma_readonly;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE app.skill_pauses;
        ALTER TABLE app.users DROP COLUMN timezone;
        """
    )
