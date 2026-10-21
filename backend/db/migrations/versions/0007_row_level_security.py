"""Row-level security (WP4.1, docs/plan/04 "Optional hardening"): every table with a `user_id`
only shows the role najma_app the rows of the user named by the `app.user_id` setting.

Per-user transactions switch to najma_app with `user_scope()` (backend/db/twin_store.py). The
table owner (migrations, admin and system paths such as sign-in by token) is not subject to RLS;
najma_jobs (retention, deletion) and najma_readonly (analytics) see every row by design.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Parents only: a partition (twin.events_YYYY_MM) is read through its parent's policies.
USER_TABLES = """
    SELECT n.nspname AS table_schema, c.relname AS table_name
    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE a.attname = 'user_id' AND NOT a.attisdropped AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition AND n.nspname IN ('app', 'twin', 'agent')
"""

UPGRADE = f"""
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app, twin, agent TO najma_app;
REVOKE UPDATE, DELETE, TRUNCATE ON twin.events FROM najma_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app, twin, agent TO najma_app;
DO $$
DECLARE r record;
BEGIN
    FOR r IN {USER_TABLES} LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
                       r.table_schema, r.table_name);
        EXECUTE format(
            'CREATE POLICY own_rows ON %I.%I TO najma_app'
            ' USING (user_id = nullif(current_setting(''app.user_id'', true), '''')::uuid)'
            ' WITH CHECK (user_id = nullif(current_setting(''app.user_id'', true), '''')::uuid)',
            r.table_schema, r.table_name);
        EXECUTE format(
            'CREATE POLICY all_rows ON %I.%I TO najma_jobs, najma_readonly USING (true)',
            r.table_schema, r.table_name);
    END LOOP;
END $$;
"""

DOWNGRADE = f"""
DO $$
DECLARE r record;
BEGIN
    FOR r IN {USER_TABLES} LOOP
        EXECUTE format('DROP POLICY own_rows ON %I.%I', r.table_schema, r.table_name);
        EXECUTE format('DROP POLICY all_rows ON %I.%I', r.table_schema, r.table_name);
        EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
                       r.table_schema, r.table_name);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
