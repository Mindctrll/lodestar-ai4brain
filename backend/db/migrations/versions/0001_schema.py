"""Initial schema: app, twin and agent (docs/plan/04).

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = r"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA app;
CREATE SCHEMA twin;
CREATE SCHEMA agent;

-- app: users and their choices ------------------------------------------------------------

CREATE TABLE app.users (
    user_id        uuid PRIMARY KEY DEFAULT uuidv7(),
    created_at     timestamptz NOT NULL DEFAULT now(),
    display_name   text,
    persona        text NOT NULL DEFAULT 'zitouna'
                   CHECK (persona IN ('zitouna', 'barq', 'hikma', 'sahbi')),
    success_mode   text NOT NULL DEFAULT 'balanced'
                   CHECK (success_mode IN ('chill', 'balanced', 'push')),
    locale         text NOT NULL DEFAULT 'en',
    age_confirmed  boolean NOT NULL DEFAULT false
);

CREATE TABLE app.consent (
    user_id         uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    switch          text NOT NULL CHECK (switch IN ('core', 'cloud_ai', 'microphone', 'camera',
                                                    'voice_tone', 'deliberate_mistakes',
                                                    'research_export')),
    granted         boolean NOT NULL,
    notice_version  text NOT NULL,
    changed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, switch)
);

CREATE TABLE app.goals (
    goal_id     uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    dim         text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('range', 'score')),
    target      double precision NOT NULL,
    due         date NOT NULL,
    status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'met', 'missed', 'dropped')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX goals_user_idx ON app.goals (user_id, status);

CREATE TABLE app.deletion_receipts (
    receipt_id  uuid PRIMARY KEY DEFAULT uuidv7(),
    user_hash   text NOT NULL,
    counts      jsonb NOT NULL,
    deleted_at  timestamptz NOT NULL DEFAULT now()
);

-- AGENTS.md rule 9: keys are stored encrypted, shown as the last 4 characters only.
CREATE TABLE app.llm_credentials (
    credential_id       uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id             uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    provider            text NOT NULL,
    key_ciphertext      bytea NOT NULL,
    nonce               bytea NOT NULL,
    master_key_version  integer NOT NULL,
    key_last4           text NOT NULL CHECK (length(key_last4) = 4),
    status              text NOT NULL DEFAULT 'unchecked'
                        CHECK (status IN ('ok', 'rejected', 'out_of_credit', 'unchecked')),
    checked_at          timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

CREATE TABLE app.llm_selection (
    user_id     uuid PRIMARY KEY REFERENCES app.users ON DELETE CASCADE,
    mode        text NOT NULL CHECK (mode IN ('hosted', 'local', 'stub')),
    provider    text NOT NULL,
    model       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- twin: the record and the profile -------------------------------------------------------

-- Append-only, partitioned by month. The primary key includes the partition column.
CREATE TABLE twin.events (
    event_id        uuid NOT NULL DEFAULT uuidv7(),
    user_id         uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    session_id      uuid,
    ts              timestamptz NOT NULL DEFAULT now(),
    type            text NOT NULL,
    schema_version  integer NOT NULL DEFAULT 1,
    payload         jsonb NOT NULL,
    PRIMARY KEY (event_id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX events_user_ts_idx ON twin.events (user_id, ts);
CREATE INDEX events_user_type_idx ON twin.events (user_id, type);
CREATE INDEX events_session_idx ON twin.events (session_id);
CREATE TABLE twin.events_default PARTITION OF twin.events DEFAULT;

CREATE FUNCTION twin.ensure_event_partitions(months_back integer DEFAULT 1,
                                             months_ahead integer DEFAULT 3)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    m date;
    part text;
BEGIN
    FOR i IN -months_back..months_ahead LOOP
        m := (date_trunc('month', now() AT TIME ZONE 'UTC') + make_interval(months => i))::date;
        part := format('events_%s', to_char(m, 'YYYY_MM'));
        IF to_regclass('twin.' || part) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE twin.%I PARTITION OF twin.events FOR VALUES FROM (%L) TO (%L)',
                part, m::text || ' 00:00:00+00', (m + interval '1 month')::date::text || ' 00:00:00+00');
        END IF;
    END LOOP;
END $$;
SELECT twin.ensure_event_partitions();

CREATE FUNCTION twin.forbid_event_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'twin.events is append-only (%)', TG_OP USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER events_append_only BEFORE UPDATE ON twin.events
    FOR EACH ROW EXECUTE FUNCTION twin.forbid_event_change();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON twin.events
    FOR EACH STATEMENT EXECUTE FUNCTION twin.forbid_event_change();

CREATE TABLE twin.rounds (
    round_id    uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    session_id  uuid NOT NULL,
    game_id     text NOT NULL,
    level       double precision NOT NULL CHECK (level BETWEEN 0 AND 1),
    score       double precision,
    status      text NOT NULL DEFAULT 'started'
                CHECK (status IN ('started', 'completed', 'stopped', 'eased', 'abandoned')),
    started_at  timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz,
    scored_at   timestamptz
);
CREATE INDEX rounds_user_idx ON twin.rounds (user_id, started_at);
CREATE INDEX rounds_session_idx ON twin.rounds (session_id);

CREATE TABLE twin.trials (
    trial_id     uuid PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    session_id   uuid NOT NULL,
    round_id     uuid NOT NULL REFERENCES twin.rounds ON DELETE CASCADE,
    game_id      text NOT NULL,
    level        double precision NOT NULL CHECK (level BETWEEN 0 AND 1),
    trial_index  integer NOT NULL CHECK (trial_index >= 0),
    practice     boolean NOT NULL DEFAULT false,
    correct      boolean,
    rt_ms        double precision CHECK (rt_ms >= 0),
    hint_level   integer NOT NULL DEFAULT 0 CHECK (hint_level >= 0),
    confidence   double precision CHECK (confidence BETWEEN 0 AND 1),
    stimulus     jsonb NOT NULL,
    response     jsonb,
    ts           timestamptz NOT NULL
);
CREATE INDEX trials_user_ts_idx ON twin.trials (user_id, ts);
CREATE INDEX trials_round_idx ON twin.trials (round_id);

CREATE TABLE twin.dimension_state (
    user_id         uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    dim             text NOT NULL,
    mu              double precision NOT NULL,
    sigma           double precision NOT NULL CHECK (sigma > 0),
    n               integer NOT NULL DEFAULT 0 CHECK (n >= 0),
    last_practised  timestamptz,
    last_event_id   uuid,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, dim)
);

CREATE TABLE twin.history (
    user_id  uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    day      date NOT NULL,
    dim      text NOT NULL,
    mu       double precision NOT NULL,
    sigma    double precision NOT NULL CHECK (sigma > 0),
    n        integer NOT NULL CHECK (n >= 0),
    PRIMARY KEY (user_id, day, dim)
);

-- Shared across users (docs/plan/07).
CREATE TABLE twin.item_difficulty (
    game_id     text NOT NULL,
    level_key   text NOT NULL,
    b           double precision NOT NULL,
    n           integer NOT NULL DEFAULT 0 CHECK (n >= 0),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, level_key)
);

CREATE TABLE twin.acs_observations (
    obs_id     uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id    uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    component  text NOT NULL CHECK (component IN ('V', 'A', 'I', 'C', 'R')),
    success    boolean NOT NULL,
    source     text NOT NULL,
    round_id   uuid,
    ts         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX acs_user_component_idx ON twin.acs_observations (user_id, component);

CREATE TABLE twin.life_context (
    context_id  uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    label       text NOT NULL,
    period      tstzrange NOT NULL CHECK (NOT isempty(period)),
    weight      double precision NOT NULL DEFAULT 0.5 CHECK (weight BETWEEN 0 AND 1)
);
CREATE INDEX life_context_user_period_idx ON twin.life_context USING gist (user_id, period);

-- agent: what Najma did and why ----------------------------------------------------------

CREATE TABLE agent.sessions (
    session_id  uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    trigger     text NOT NULL CHECK (trigger IN ('voice', 'ui', 'cli', 'schedule', 'proactive')),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'ended')),
    started_at  timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz
);
CREATE INDEX sessions_user_idx ON agent.sessions (user_id, started_at);

CREATE TABLE agent.decisions (
    decision_id  uuid PRIMARY KEY,
    session_id   uuid NOT NULL,
    user_id      uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    node         text NOT NULL,
    question     text NOT NULL,
    candidates   jsonb NOT NULL,
    chosen       text NOT NULL,
    reason       text NOT NULL CHECK (length(reason) > 0),
    evidence     text[] NOT NULL DEFAULT '{}',
    ts           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decisions_user_ts_idx ON agent.decisions (user_id, ts);
CREATE INDEX decisions_session_idx ON agent.decisions (session_id);

CREATE TABLE agent.traces (
    session_id  uuid NOT NULL,
    seq         integer NOT NULL,
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    node        text NOT NULL,
    event       text NOT NULL,
    ms          double precision,
    tokens      integer,
    payload     jsonb,
    ts          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX traces_ts_idx ON agent.traces (ts);

CREATE TABLE agent.experiments (
    exp_id      uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id     uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    hypothesis  text NOT NULL,
    design      jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'running', 'completed', 'inconclusive', 'cancelled')),
    result      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX experiments_user_idx ON agent.experiments (user_id, status);

CREATE TABLE agent.content_pool (
    item_id           uuid PRIMARY KEY DEFAULT uuidv7(),
    game_id           text NOT NULL,
    level             double precision NOT NULL CHECK (level BETWEEN 0 AND 1),
    content           jsonb NOT NULL,
    validator_report  jsonb NOT NULL,
    prompt_version    text,
    model             text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX content_pool_game_level_idx ON agent.content_pool (game_id, level);

CREATE TABLE agent.content_served (
    user_id    uuid NOT NULL REFERENCES app.users ON DELETE CASCADE,
    item_id    uuid NOT NULL REFERENCES agent.content_pool ON DELETE CASCADE,
    served_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE agent.ml_models (
    model_id       uuid PRIMARY KEY DEFAULT uuidv7(),
    name           text NOT NULL,
    version        text NOT NULL,
    metrics        jsonb NOT NULL,
    artefact_path  text NOT NULL,
    trained_at     timestamptz NOT NULL,
    active         boolean NOT NULL DEFAULT false,
    UNIQUE (name, version)
);
CREATE UNIQUE INDEX ml_models_one_active_idx ON agent.ml_models (name) WHERE active;

-- Roles (docs/plan/04, optional hardening). NOLOGIN group roles; the app is switched to them in
-- WP4.1. najma_app can never UPDATE, DELETE or TRUNCATE the event log.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'najma_app') THEN
        CREATE ROLE najma_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'najma_jobs') THEN
        CREATE ROLE najma_jobs NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'najma_readonly') THEN
        CREATE ROLE najma_readonly NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA app, twin, agent TO najma_app, najma_jobs, najma_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app, twin, agent TO najma_app;
REVOKE UPDATE, DELETE, TRUNCATE ON twin.events FROM najma_app;
GRANT SELECT, INSERT, DELETE ON ALL TABLES IN SCHEMA app, twin, agent TO najma_jobs;
GRANT SELECT ON ALL TABLES IN SCHEMA app, twin, agent TO najma_readonly;
"""

DROP = r"""
DROP SCHEMA agent CASCADE;
DROP SCHEMA twin CASCADE;
DROP SCHEMA app CASCADE;
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute(DROP)
