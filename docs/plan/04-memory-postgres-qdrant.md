# 04 · Memory and storage: Postgres + Qdrant

Decision: **Postgres for all structured data, Qdrant for searchable memory, Markdown files only for Najma's readable notes.** No JSON or JSONL files, no SQLite.

## Three kinds of memory

| Kind | Question it answers | Where it lives |
|---|---|---|
| **Record** (what happened) | Every trial, round, session, consent change | Postgres `twin.events` (append-only) |
| **Profile** (who you are now) | Current skill estimates, history, goals, settings | Postgres projection tables, rebuilt from events |
| **Recall** (what to remember) | "You said exams start Monday", "you get frustrated with timed games" | Qdrant (searchable) + Markdown notes (readable) |

The event table is the source of truth. The profile tables are projections of it, so we can wipe a user's projections and rebuild them by replaying events, which the robustness tests do.

## Stack

| Piece | Choice |
|---|---|
| Database | PostgreSQL 18 in Docker |
| Driver | `psycopg` 3.3 + `psycopg-pool` (async) |
| Queries | SQLAlchemy 2.1 Core (no ORM magic in hot paths) |
| Migrations | Alembic; every schema change is a migration in the repo |
| LangGraph checkpoints | `langgraph-checkpoint-postgres` 3.2 (`AsyncPostgresSaver`) on its own `psycopg-pool` (SQLAlchemy keeps its pool; both point at the same database); `setup()` runs in Alembic revision 0002 |
| Long-term semantic memory | Qdrant, through our `QdrantStore(BaseStore)` (`03`) |

## Schemas and tables

Four Postgres schemas keep things tidy: `app`, `twin`, `agent`, plus the tables LangGraph creates for checkpoints.

### `app`: users and their choices

| Table | Key columns | Notes |
|---|---|---|
| `users` | `user_id uuid pk`, `created_at`, `display_name` (optional, never sent to an LLM), `persona`, `success_mode`, `locale`, `age_confirmed` | Every other table references this with `ON DELETE CASCADE` |
| `consent` | `user_id`, `switch`, `granted`, `notice_version`, `changed_at` | Current state; history is in events |
| `goals` | `goal_id`, `user_id`, `dim`, `kind`, `target`, `due`, `status` | e.g. "WM range ±5 by 7 Nov" |
| `user_tokens` | `token_hash pk`, `user_id`, `created_at`, `last_used` | Bearer tokens for the API; only a SHA-256 hash is stored |
| `deletion_receipts` | `receipt_id`, `user_hash`, `counts jsonb`, `deleted_at` | Counts only, no personal content |
| `llm_credentials` | `credential_id pk`, `unique (user_id, provider)`, `key_ciphertext bytea`, `nonce bytea`, `master_key_version`, `key_last4`, `status`, `checked_at`, `created_at` | AES-GCM with a server master key from the environment (`NAJMA_MASTER_KEY`); the version allows rotation. Never exported, never logged (`AGENTS.md` rule 9) |
| `llm_selection` | `user_id pk`, `mode` (`hosted` or `local`), `provider`, `model`, `updated_at` | The active choice; `local` = Ollama |

### `twin`: the record and the profile

| Table | Key columns | Notes |
|---|---|---|
| `events` | `event_id uuid default uuidv7()` (native in Postgres 18, sorts by time), `user_id`, `session_id`, `ts timestamptz`, `primary key (event_id, ts)` (a partitioned table's key must include the partition column), `type`, `schema_version`, `payload jsonb` | **Append-only.** Partitioned by month. A trigger blocks `UPDATE`; `DELETE` only by the deletion and retention jobs' role |
| `trials` | `trial_id`, `user_id`, `session_id`, `round_id`, `game_id`, `level`, `correct`, `rt_ms`, `hint_level`, `confidence`, `stimulus jsonb`, `response jsonb`, `ts` | Typed copy for analytics and charts; written in the same transaction as the event |
| `rounds` | `round_id pk`, `user_id`, `session_id`, `game_id`, `level`, `score`, `status`, `started_at`, `ended_at`, `scored_at` | Created with status `started` when the exercise is issued, so trials can reference it and a half-played game can be resumed (UW6). The primary key on `round_id` makes score updates idempotent |
| `dimension_state` | `(user_id, dim) pk`, `mu`, `sigma`, `n`, `last_practised`, `last_event_id`, `updated_at` | The current Brain Twin (projection) |
| `history` | `(user_id, day, dim) pk`, `mu`, `sigma`, `n` | One row per user, day and skill: the mandatory history, used for curves |
| `item_difficulty` | `(game_id, level_key) pk`, `b`, `n`, `updated_at` | Shared across users (`07`) |
| `acs_observations` | `user_id`, `component`, `success`, `source`, `ts` | Input to the ACS (`11`) |
| `life_context` | `context_id`, `user_id`, `label`, `period tstzrange`, `weight` | "Exam week"; GiST index on `period` for "is this trial inside a window?" |

### `agent`: what Najma did and why

| Table | Key columns | Notes |
|---|---|---|
| `sessions` | `session_id pk`, `user_id`, `trigger`, `status`, `started_at`, `ended_at` | Lists a user's LangGraph threads for deletion, and the paused session to resume |
| `decisions` | `decision_id`, `session_id`, `user_id`, `node`, `question`, `candidates jsonb`, `chosen`, `reason`, `evidence text[]`, `ts` | The explainability log; the why cards read from here |
| `traces` | `(session_id, seq) pk`, `user_id`, `node`, `event`, `ms`, `tokens`, `payload jsonb`, `ts` | Agent timeline and trace viewer |
| `experiments` | `exp_id`, `user_id`, `hypothesis`, `design jsonb`, `status`, `result jsonb`, `created_at` | Personal experiments (`09`) |
| `content_pool` | `item_id`, `game_id`, `level`, `content jsonb`, `validator_report jsonb`, `prompt_version`, `created_at` | Pre-generated game content (`08`) |
| `content_served` | `user_id`, `item_id`, `served_at` | So nobody gets the same item twice |
| `ml_models` | `model_id`, `name`, `version`, `metrics jsonb`, `artefact_path`, `trained_at`, `active` | Model registry; artefacts are binary model files on disk |

`jsonb` columns hold flexible payloads inside Postgres; nothing is stored as loose JSON files.

### LangGraph checkpoints

`AsyncPostgresSaver` creates and manages its own tables. Thread id = `session_id`. We get durable pauses during games, time travel (replay any session from any checkpoint) and `adelete_thread` for deletion, with no custom code.

## How writes work

- **One transaction per scored round:** insert events → insert trials → update `rounds` → update `dimension_state` → upsert `twin.history`. Either all of it happens or none of it does.
- **Per-user lock** inside that transaction: `pg_advisory_xact_lock(hashtext(user_id))`, so two tabs can't update the same profile at once.
- **Idempotency:** a repeated resume with the same `round_id` hits the unique constraint and is ignored.
- **Live dashboard:** after commit, `NOTIFY twin_updated, '<user_id>'`; the API `LISTEN`s and pushes to that user's WebSocket.
- **Rebuild:** `make rebuild-twin USER=<id>` deletes the user's projection rows and replays `twin.events` in `event_id` order, starting from the user's latest `twin.snapshot` event if one exists. Used in tests. Each `twin.updated` event carries the after-state of every skill it changed and the scoring inputs that aren't in the trials (learned item difficulties, context weight, trust), because shared item difficulties keep changing as other users play; with those, a re-score of the raw trials reproduces the recorded update.

### Event types

`session.started`, `trial.recorded`, `round.completed`, `twin.updated`, `acs.observed`, `affect.estimated` (behaviour only, with a flag if a camera signal was used), `affect.labelled` (mood check, "Was I right?"), `context.added`, `goal.set`, `experiment.*`, `consent.changed`, `memory.written`, `session.ended`, `data.exported`, `twin.snapshot` (see Retention below), `llm.selection_changed` (provider and model only, never the key).

## Dashboard queries come straight from SQL

- **Curves:** `twin.history` by user and skill.
- **Heatmap skill × week:** `count(*)` and change in μ grouped by `date_trunc('week', ts)`.
- **Heatmap time of day × weekday:** `extract(hour)`, `extract(dow)` over `trials`.
- **ACS:** sums per component from `acs_observations`.

Add views or materialised views for the heavier ones, refreshed after each session.

## Najma's readable notes (Markdown, the only files)

```
memory/<user_id>/
  core.md                    # stable facts Najma maintains about the user
  journal/2026-10-21.md      # human-readable session summaries
```

```markdown
# Core memory — Amira
- Prefers the Zitouna persona; asked for fewer timed games (2026-10-22)
- Goal: raise working memory confidence to ±5 by 7 Nov
- Usually plays in the evening, around 21:00
- Exams: 3–14 Nov (life context; bad days down-weighted)
```

Najma reads `core.md` at the start of every session and rewrites it during consolidation. Users can view and edit it in settings, so they see exactly what Najma remembers. Writes are atomic (temp file, then rename).

## Qdrant

Qdrant server 1.19 in Docker, `qdrant-client` 1.19 (keep client and server on the same minor version).

### Collections

| Collection | One point = | Vectors | Key payload |
|---|---|---|---|
| `episodic` | A memorable moment or session summary | `dense` (bge-small, 384, cosine) + `sparse` (BM25) | `user_id`, `kind`, `created_at`, `importance`, `dims[]`, `source_event_ids[]`, `expires_at` |
| `facts` | A distilled fact or preference ("focuses better in the morning, 70% confidence") | dense + sparse | `user_id`, `confidence`, `valid_from`, `valid_to`, `superseded_by` |
| `knowledge` | A curated tip or explanation per skill, written by the team, with references. **Shared, no user data** | dense + sparse | `dim`, `source_url`, `evidence_level` |
| `exercises` | One item served to one user (for novelty checks) | dense | `user_id`, `game_id`, `level`, `item_id` (links to `agent.content_pool`), `served_at` |

Payload indexes: `user_id` (keyword, tenant index), `kind`, `dims`, `created_at` (datetime), `importance` (float). Each Qdrant point's `source_event_ids` link back to rows in `twin.events`, so every memory can be traced to what actually happened.

### Retrieval recipe

One `query_points` call:

1. **Prefetch** dense top-30 and sparse top-30, both filtered by `user_id`.
2. **Fuse** with reciprocal rank fusion (RRF).
3. **Rescore** with a formula: fused rank × relevance gate × importance × time decay on `created_at`. The gate is the dense cosine rescaled from 0.55 (where unrelated short texts sit with bge-small) to 1, because fusion ranks carry no absolute relevance; the decay has a floor of 0.25 so a relevant old memory still counts.
4. **Diversify** with MMR so the top 5 aren't five versions of the same memory.

Every call goes through `memory.search(user_id, ...)`, which always adds the `user_id` filter. The shared `knowledge` collection has its own read-only helper, `memory.search_knowledge(...)`, and holds no user data.

### What gets remembered

| Signal | Example | Weight |
|---|---|---|
| The user stated something about themselves | "I have exams next week" | high |
| Strong emotion or a stopped game | quit after 5 misses | medium |
| A personal best or big change | biggest jump in a skill | medium |
| A decision the user pushed back on | "No, I don't want memory today" | medium |
| Routine round with nothing new | — | not stored in Qdrant (still in `twin.events`) |

### Consolidation ("sleep") at session end

1. Write the journal entry (Markdown) and one `episodic` point.
2. Merge near-duplicate memories (cosine > 0.92 within the user's points).
3. Promote repeated patterns to `facts` with a confidence; mark contradicted facts `superseded_by`.
4. Rewrite `core.md` from the top facts.
5. Lower the importance of old, unused memories; delete expired ones.

## Export and deletion

- **Export:** generated on request: rows from every table for that user, their Qdrant points and their Markdown notes, bundled as a download. Nothing is written to disk on the server. API keys are left out; the export lists only which providers have a key and their last 4 characters.
- **Delete, in one job:** `DELETE FROM app.users WHERE user_id = …` (cascades through every table), `adelete_thread` for each of their sessions, delete Qdrant points by `user_id` filter, remove `memory/<user_id>/`, then insert a row in `app.deletion_receipts` with counts. The UI shows the receipt.
- **Retention:** before a monthly partition of `twin.events` older than 12 months is dropped, the job writes one `twin.snapshot` event per affected user (their `dimension_state` and `history` rows at that point) into the current partition, so the profile can still be rebuilt from events. Traces and checkpoints older than 30 days are deleted by a daily job (`14`).

## Optional hardening (P2)

- **Row-level security** on every table with `user_id`: the API sets `app.user_id` per request, so a bug can't read another user's rows.
- Separate database roles: `app_rw` (no UPDATE on events), `jobs` (retention and deletion), `readonly` (analytics).

## Why Postgres

- Transactions make a scored round all-or-nothing, which keeps the profile and the record in sync.
- Constraints, locks and idempotency come built in instead of hand-written file locking.
- The dashboard's curves and heatmaps are simple SQL.
- `jsonb` keeps flexible payloads without loose files.
- LangGraph has an official, maintained Postgres checkpointer.
- Deletion is one cascade plus Qdrant and LangGraph calls, which is easy to prove for the Safety criterion.
