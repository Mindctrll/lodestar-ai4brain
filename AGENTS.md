# Rules for coding agents

These rules apply to every coding agent (and every human) working in this repo. The plan lives in `docs/plan/`; a number like `04` means `docs/plan/04-*.md`.

## Hard rules

1. **Postgres for structured data, Qdrant for memory search, Markdown for Lodestar's notes.** No JSON or JSONL files for storage, no SQLite. Flexible payloads go in `jsonb` columns. Every schema change is an Alembic migration (see `04`).
2. **Clinical words are banned in user-facing text.** See the list in `09`. Run `make lint-language` before committing UI copy or prompts.
3. **Camera and voice-tone signals never write to the Brain Twin.** There is no code path from `affect.biometric.*` to `profile.*`. A test enforces this.
4. **Every number the coach says must come from a facts packet.** See `09`.
5. **Every prediction is shown as a range,** never a single number.
6. **A scored round is one transaction** (events, trials, round, profile, history) with a per-user advisory lock. Never update `twin.events`; it's append-only.
7. **Every Qdrant query on user data filters by `user_id`.** A helper enforces this; never call the client directly from feature code. The shared `knowledge` collection (team-written tips, no user data) is the only exception and has its own read-only helper.
8. **English only** in the UI, docs and repo (challenge rule).
9. **User API keys are secrets.** They are stored encrypted in `app.llm_credentials` and decrypted only inside the LLM factory. Never put a key in graph state, runtime context, checkpoints, traces, logs, events, exports or error messages. The UI shows only the last 4 characters. A test enforces this.

## Conventions

- Python 3.14, FastAPI, LangGraph 1.2.x, Pydantic v2, `ruff` + `mypy --strict` on `backend/agent` and `backend/scoring`.
- TypeScript 6.0 strict (not 7 until typescript-eslint supports it), React 19, Vite 8, Tailwind 4 (CSS-first config), ESLint 10 flat config + Prettier.
- Use exactly the versions pinned in `02` (Pinned versions); upgrade only through a dedicated work package.
- Every jsPsych plugin lives in `frontend/src/games/<game-id>/` with `plugin.ts`, `config.yaml`, `README.md` (paradigm source, metrics, difficulty knobs).
- Every new dimension or game is registered in YAML (`registry/`) before any code. The registry drives the UI, the scorer and the agent.
- Tests: `pytest` for backend, `vitest` for frontend. The simulator (`15`) runs in CI on 200 simulated users and must pass its thresholds.
- Commit messages: `area: what changed` (e.g. `scoring: add staleness drift`).

## Definition of done for a feature

- Works in the non-biometric mode.
- Has a test.
- Writes events to the event log, not only to in-memory state.
- If user-facing: has copy reviewed against the language rules and a "why" where a decision is shown.
