"""SQLAlchemy Core tables mirroring migration 0001. Used for queries only; the migration is the
source of truth, and tests/backend/db/test_schema.py checks that these columns match it."""

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    Double,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID
from sqlalchemy.types import TIMESTAMP

metadata = MetaData()

TZ = TIMESTAMP(timezone=True)
NOW = text("now()")
UUIDV7 = text("uuidv7()")


def _uuid_pk(name: str, generated: bool = True) -> Column[object]:
    return Column(
        name, UUID(as_uuid=True), primary_key=True, server_default=UUIDV7 if generated else None
    )


def _user_fk() -> Column[object]:
    return Column("user_id", UUID(as_uuid=True), nullable=False)


# app --------------------------------------------------------------------------------------

users = Table(
    "users",
    metadata,
    _uuid_pk("user_id"),
    Column("created_at", TZ, nullable=False, server_default=NOW),
    Column("display_name", Text),
    Column("persona", Text, nullable=False, server_default="zitouna"),
    Column("success_mode", Text, nullable=False, server_default="balanced"),
    Column("locale", Text, nullable=False, server_default="en"),
    Column("age_confirmed", Boolean, nullable=False, server_default=text("false")),
    schema="app",
)

consent = Table(
    "consent",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("switch", Text, primary_key=True),
    Column("granted", Boolean, nullable=False),
    Column("notice_version", Text, nullable=False),
    Column("changed_at", TZ, nullable=False, server_default=NOW),
    schema="app",
)

goals = Table(
    "goals",
    metadata,
    _uuid_pk("goal_id"),
    _user_fk(),
    Column("dim", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("target", Double, nullable=False),
    Column("due", Date, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("created_at", TZ, nullable=False, server_default=NOW),
    schema="app",
)

deletion_receipts = Table(
    "deletion_receipts",
    metadata,
    _uuid_pk("receipt_id"),
    Column("user_hash", Text, nullable=False),
    Column("counts", JSONB, nullable=False),
    Column("deleted_at", TZ, nullable=False, server_default=NOW),
    schema="app",
)

llm_credentials = Table(
    "llm_credentials",
    metadata,
    _uuid_pk("credential_id"),
    _user_fk(),
    Column("provider", Text, nullable=False),
    Column("key_ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("master_key_version", Integer, nullable=False),
    Column("key_last4", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="unchecked"),
    Column("checked_at", TZ),
    Column("created_at", TZ, nullable=False, server_default=NOW),
    schema="app",
)

llm_selection = Table(
    "llm_selection",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("mode", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("updated_at", TZ, nullable=False, server_default=NOW),
    schema="app",
)

# twin -------------------------------------------------------------------------------------

events = Table(
    "events",
    metadata,
    Column("event_id", UUID(as_uuid=True), primary_key=True, server_default=UUIDV7),
    _user_fk(),
    Column("session_id", UUID(as_uuid=True)),
    Column("ts", TZ, primary_key=True, server_default=NOW),
    Column("type", Text, nullable=False),
    Column("schema_version", Integer, nullable=False, server_default="1"),
    Column("payload", JSONB, nullable=False),
    schema="twin",
)

rounds = Table(
    "rounds",
    metadata,
    _uuid_pk("round_id", generated=False),
    _user_fk(),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("game_id", Text, nullable=False),
    Column("level", Double, nullable=False),
    Column("score", Double),
    Column("status", Text, nullable=False, server_default="started"),
    Column("started_at", TZ, nullable=False, server_default=NOW),
    Column("ended_at", TZ),
    Column("scored_at", TZ),
    schema="twin",
)

trials = Table(
    "trials",
    metadata,
    _uuid_pk("trial_id", generated=False),
    _user_fk(),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("game_id", Text, nullable=False),
    Column("level", Double, nullable=False),
    Column("trial_index", Integer, nullable=False),
    Column("practice", Boolean, nullable=False, server_default=text("false")),
    Column("correct", Boolean),
    Column("rt_ms", Double),
    Column("hint_level", Integer, nullable=False, server_default="0"),
    Column("confidence", Double),
    Column("stimulus", JSONB, nullable=False),
    Column("response", JSONB),
    Column("ts", TZ, nullable=False),
    schema="twin",
)

dimension_state = Table(
    "dimension_state",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("dim", Text, primary_key=True),
    Column("mu", Double, nullable=False),
    Column("sigma", Double, nullable=False),
    Column("n", Integer, nullable=False, server_default="0"),
    Column("last_practised", TZ),
    Column("last_event_id", UUID(as_uuid=True)),
    Column("updated_at", TZ, nullable=False, server_default=NOW),
    schema="twin",
)

history = Table(
    "history",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("dim", Text, primary_key=True),
    Column("mu", Double, nullable=False),
    Column("sigma", Double, nullable=False),
    Column("n", Integer, nullable=False),
    schema="twin",
)

item_difficulty = Table(
    "item_difficulty",
    metadata,
    Column("game_id", Text, primary_key=True),
    Column("level_key", Text, primary_key=True),
    Column("b", Double, nullable=False),
    Column("n", Integer, nullable=False, server_default="0"),
    Column("updated_at", TZ, nullable=False, server_default=NOW),
    schema="twin",
)

acs_observations = Table(
    "acs_observations",
    metadata,
    _uuid_pk("obs_id"),
    _user_fk(),
    Column("component", Text, nullable=False),
    Column("success", Boolean, nullable=False),
    Column("source", Text, nullable=False),
    Column("round_id", UUID(as_uuid=True)),
    Column("ts", TZ, nullable=False, server_default=NOW),
    schema="twin",
)

life_context = Table(
    "life_context",
    metadata,
    _uuid_pk("context_id"),
    _user_fk(),
    Column("label", Text, nullable=False),
    Column("period", TSTZRANGE, nullable=False),
    Column("weight", Double, nullable=False, server_default="0.5"),
    schema="twin",
)

# agent ------------------------------------------------------------------------------------

sessions = Table(
    "sessions",
    metadata,
    _uuid_pk("session_id"),
    _user_fk(),
    Column("trigger", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("started_at", TZ, nullable=False, server_default=NOW),
    Column("ended_at", TZ),
    schema="agent",
)

decisions = Table(
    "decisions",
    metadata,
    _uuid_pk("decision_id", generated=False),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    _user_fk(),
    Column("node", Text, nullable=False),
    Column("question", Text, nullable=False),
    Column("candidates", JSONB, nullable=False),
    Column("chosen", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("evidence", ARRAY(Text), nullable=False, server_default="{}"),
    Column("ts", TZ, nullable=False, server_default=NOW),
    schema="agent",
)

traces = Table(
    "traces",
    metadata,
    Column("session_id", UUID(as_uuid=True), primary_key=True),
    Column("seq", Integer, primary_key=True),
    _user_fk(),
    Column("node", Text, nullable=False),
    Column("event", Text, nullable=False),
    Column("ms", Double),
    Column("tokens", Integer),
    Column("payload", JSONB),
    Column("ts", TZ, nullable=False, server_default=NOW),
    schema="agent",
)

experiments = Table(
    "experiments",
    metadata,
    _uuid_pk("exp_id"),
    _user_fk(),
    Column("hypothesis", Text, nullable=False),
    Column("design", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default="proposed"),
    Column("result", JSONB),
    Column("created_at", TZ, nullable=False, server_default=NOW),
    Column("updated_at", TZ, nullable=False, server_default=NOW),
    schema="agent",
)

content_pool = Table(
    "content_pool",
    metadata,
    _uuid_pk("item_id"),
    Column("game_id", Text, nullable=False),
    Column("level", Double, nullable=False),
    Column("content", JSONB, nullable=False),
    Column("validator_report", JSONB, nullable=False),
    Column("prompt_version", Text),
    Column("model", Text),
    Column("created_at", TZ, nullable=False, server_default=NOW),
    schema="agent",
)

content_served = Table(
    "content_served",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("item_id", UUID(as_uuid=True), primary_key=True),
    Column("served_at", TZ, nullable=False, server_default=NOW),
    schema="agent",
)

ml_models = Table(
    "ml_models",
    metadata,
    _uuid_pk("model_id"),
    Column("name", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("metrics", JSONB, nullable=False),
    Column("artefact_path", Text, nullable=False),
    Column("trained_at", TZ, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("false")),
    schema="agent",
)

# Tables holding one user's data, deleted by the cascade from app.users (docs/plan/14).
USER_TABLES: tuple[Table, ...] = (
    consent,
    goals,
    llm_credentials,
    llm_selection,
    events,
    rounds,
    trials,
    dimension_state,
    history,
    acs_observations,
    life_context,
    sessions,
    decisions,
    traces,
    experiments,
    content_served,
)
