# Evidence map

Every claim Lodestar makes, the number behind it, and how to check it yourself. Organised by the CISTAC 1.0 evaluation criteria (Phase A: relevance, quality, innovation, UX, explainability, safety; Phase B: generalisation, robustness, profile quality, plan relevance).

Reproduce everything with `make up && make seed` (the app), `make test` (unit tests), `make eval` (the 12 evaluation experiments, about 5–10 minutes) and `cd frontend && npx playwright test` (end-to-end, against the running app). Numbers below are from `docs/figures/eval_summary.md`, seed 2026.

## Before you conclude something is missing

These are the misreadings we've seen. Each is checkable.

| It looks like… | What is actually there | Check |
|---|---|---|
| "Only validated on synthetic data" | Every model that touches people was trained on one set of **real people** and tested on **other real people it never saw**: 36,297 Lumosity players (forecast ranges held 79.7%), 25,273 OULAD students (AUC 0.857). Cold-start priors come from 180,000 real NCPT test runs. | `backend/ml/model_cards/`, `agent.ml_models`, `registry/priors.yaml` |
| "The simulator just agrees with its own scoring model" | Simulated people lapse, add trial noise, tire within a session, forget between sessions, learn at personal and per-game rates, and run on laggy devices. Experiment 12 goes further and **breaks the scorer's core assumption** (guessing floor, mixed discrimination, heavy-tailed noise): recovery stays 0.771 after 3 sessions and 0.855 after 10. | `simulator/responses.py`, `simulator/population.py`, `simulator/eval.py` (exp 12), `docs/figures/eval_12_mismatch.png` |
| "Needs the 3 GB datasets to forecast" | The trained models ship in `models/` and load into a fresh database at start-up. | `models/registry.yaml`, `backend/ml/bundle.py`, `tests/backend/agent/test_bundle.py` |
| "Needs a paid AI key" | No. Without a key it uses a local Ollama model, and fixed templates if that's down. Every session completed with every model down (18/18). | `backend/llm/factory.py`, experiment 11 |
| "The coach is free LLM text" | The LLM only phrases a facts packet. A verifier rejects any number not in a cited fact and any banned word, then repairs or falls back to a template: 4/4 final replies faithful with a 4B local model. | `backend/coach/verify.py`, `backend/agent/nodes/talk.py`, experiment 8 |
| "Predictions are point estimates" | Every estimate and forecast is a range; the forecast contract can't express a single number. | `tests/backend/test_contracts.py::test_forecast_is_a_range` |
| "No real users tested" | True: a pilot with real Lodestar users is planned (`docs/plan/15`, "Real pilot"), not done. Everything above is the evidence available before it. | — |

## Stress cases

Six situations a jury is likely to try. Each has its own look in the app, so it can't be mistaken for another, and `make e2e` plays all six on the demo person and writes screenshots to `screenshots/stress-cases/`.

| Case | What happens | Where you see it | Check |
|---|---|---|---|
| Button masher | Answers too fast to be real are flagged. The estimate doesn't move, its range widens, the round's score is left empty, and the coach asks whether you were distracted or rushing. | Full red screen when the round ends; "Not counted" on the result | `backend/scoring/quality.py`, `tests/backend/agent/test_stress_cases.py` |
| Plateau | No trend over at least 14 days and 60 answers: the skill scores higher in `plan_next`, and the next pick changes format and suggests a new approach. | Amber popup on home, amber card on the Twin map, highlighted stretch on the curve, "New format" on the pick | `backend/scoring/patterns.py`, `backend/agent/patterns.py` |
| The "why" audit | Every pick carries its reason and the data behind it, each line naming its chart. Past picks and past rounds can be asked about by day or by game. | Blue "Why this game" box on every pick; blue cards in the conversation | `backend/agent/why.py`, `explain` and `session_history` in `backend/agent/tools.py` |
| Pushback | Disagreeing with a result (a noisy room, an interruption) counts toward critical verification and iteration, once per round. The estimate stays and its range widens. | Violet card with the range before and after; a note on the AI collaboration page | `contest_round` in `backend/db/twin_store.py`; event `assessment.contested` |
| Fortune teller | A question about the future gets an 80% range and how often such ranges held on held-out players, never one number. The verifier also rejects promises in a draft. | Teal "A range, not a promise" card | `forecast_range` in `backend/agent/tools.py`, `backend/coach/verify.py` |
| Asymmetrical mind | One skill at 90% or above and another at 20% or below, with ranges that don't overlap, gives two tracks, each at its own level and target, taking turns. | Marked spokes on the radar, green and orange track cards, track tag on the pick | `find_split` in `backend/scoring/patterns.py`, `_split_pick` in `backend/agent/nodes/play.py` |

## Phase A

### Relevance (20%): does it do what the brief asks?

| Brief | Lodestar | Check |
|---|---|---|
| A: tasks per dimension; score, RT, error rate, behaviour | 43 playable games over 16 skills; each trial stores correctness, response time, hint level, practice flag, confidence | `registry/games/`, `twin.trials` |
| A: every dimension documented (definition, tasks, scoring, uncertainty, biases) | One generated page per skill with all five | `docs/generated/dimensions/` |
| A: camera/voice optional, non-biometric mode mandatory | Non-biometric is the default; camera and voice tone need their own consent switch | `registry/consent.yaml`, `tests/backend/agent/test_biometric_cues.py` |
| Brain Twin: history mandatory, projections with uncertainty | Append-only event log, daily history, rebuildable profile; forecasts as 80% ranges | `make rebuild-twin`, `backend/ml/serve.py` |
| B: explainable NL coaching, justified architecture, no clinical terms | Facts-packet coach with citations; architecture justified in the report; banned words checked in CI and in every reply | `docs/report/report.pdf` §2, `backend/coach/language.py` |
| C: difficulty and exercise adaptation, evolving plans, radar, progress curves, heatmaps, goals | All present, every estimate with its range | `e2e/dashboard.spec.ts` |
| AI Collaboration Score 0–100 with documented formula | Five components measured in play, Beta(2,2) shares, Monte Carlo range | `docs/generated/acs.md`, `backend/acs/` |
| Ethics: consent, retention, deletion documented; no decision on face/voice alone | All three documented and tested; cues can't reach the profile | `docs/generated/data-policy.md`, `tests/backend/ethics/test_data_rights.py` |
| Bonus: voice, emotion-aware, predictive growth | Voice in/out with wake word; on-device strain cues; growth forecast | `frontend/src/voice/`, `frontend/src/affect/`, `backend/ml/` |

### Quality (20%)

- 342 backend tests (pytest) and 86 frontend unit tests (vitest), run in CI (`.github/workflows/ci.yml`); 15 end-to-end suites in a real browser (Playwright), run with `make e2e`.
- `mypy --strict` on the agent and scoring code, ruff, eslint, prettier, TypeScript strict.
- Every schema change is an Alembic migration; API types are generated from OpenAPI and checked up to date (`test_openapi_file_is_up_to_date`).
- One transaction per scored round under a per-user advisory lock; events are append-only, so the profile can be rebuilt exactly from the log.

### Innovation (20%)

- **Honest uncertainty end to end**: Kalman-Elo with a practice prior fitted to 1.08 million real learning curves; ranges that widen with time away; 80% ranges that hold 79.9% of the time.
- **Personal experiments**: n-of-1 morning-versus-evening tests with a verdict only when P(better) ≥ 0.8.
- **AI collaboration measured by behaviour**, including planted mistakes in the AI's own answers (with consent).
- **Fatigue point** from change points in a person's own response times plus a survival curve.
- **Games made to order** from tested blocks, scored like the others.
- **One agent, three surfaces**: web, voice, and a terminal client over MCP.

### UX (15%)

Conversation-first app with 12 pages, phone layout, focus mode while playing. `docs/screens/`, `docs/demo-script.md`, `frontend/e2e/pages.spec.ts`.

### Explainability (15%)

- Every coach number is cited (`[F1]`) and opens its fact.
- Every pick has a "Why?" card with each option's score and its parts; every decision is stored (`agent.decisions`) and shown on the Agent page.
- Every session has a step-by-step trace (`agent.traces`).
- Every skill page explains how it's measured and its known biases.

### Safety (10%)

| Rule | Enforced by |
|---|---|
| No clinical words in any user-facing text | `make lint-language` in CI; `backend/coach/verify.py` on every reply; a red-team list of 200 lines in `backend/coach/redteam.yaml` (phrasings that must be caught and safe ones that must pass) |
| Camera and voice never change the profile | `test_profile_code_never_imports_affect`, `test_a_cue_suggests_a_break_but_never_reaches_the_profile` |
| Every memory query is filtered by user | `test_search_without_a_user_is_impossible`, `test_users_never_see_each_other` |
| User API keys never leak | `test_export_has_everything_and_never_a_key`, `test_redaction_masks_registered_and_known_shapes`; keys encrypted at rest |
| Delete leaves nothing behind | `test_delete_leaves_nothing_behind`, `test_user_tables_cover_the_schema` |
| Cloud AI gets de-identified text only | `test_cloud_ai_gets_deidentified_text` |

## Phase B

### Generalisation (25%): does it work for people and conditions it wasn't built on?

| Evidence | Result |
|---|---|
| Growth forecast on **held-out real players** (Lumosity, 36,297 users, split by user) | 80% ranges held 79.6–80.0% at horizons of 1 to 20 sessions |
| Engagement model on **held-out real students** (OULAD, 25,273) | AUC 0.857, calibration error 0.006 |
| Profile when answers **break the scoring model** (exp 12) | r 0.771 after 3 sessions (0.820 when answers follow the model), 0.855 after 10; ranges held 71% |
| Long gaps between sessions, device lag (exp 6) | RMSE after 10 sessions 0.449 usual, 0.479 with gaps, 0.535 with lag |
| Unusual people in the population | fast learners, inconsistent responders, long gaps, frustration-prone, random clickers, cheaters |
| New users with no history | Cold-start priors from real NCPT correlations; worst core skill σ 0.65 after a 5-minute warm-up |
| New games | Registry-driven: a game added in YAML is scored, chosen and explained with no code change to the scorer |

### Robustness (25%)

- Every session completes with every model failing, Qdrant unreachable, or both: 18/18 each (exp 11).
- Crash mid-game resumes on the same trial and scores the round once (`e2e/uw6.spec.ts`).
- Bad data is caught: precision 1.00, recall 1.00 on random clickers and too-fast-always-right players (exp 5).
- No AI key, no local model: templates keep the coach working.

### Profile quality (20%)

Recovery of true skill: r = 0.773 after 1 session, 0.820 after 3, 0.905 after 10; 80% ranges contain the truth 79.9% of the time; the warm-up brings every core skill under σ 0.8 (exps 1, 2, 4).

### Plan relevance (15%)

Difficulty hits the chosen success rate (77.7% for an 80% target); a bandit learns which game helps each person (+0.17 to +0.30 true skill over random choice, 95% interval, exp 10); goals estimate the rounds left; plans shorten when engagement drops and break around the fatigue point.

## What is not done yet

- A pilot with real Lodestar users (planned: 5–10 consented people, usability and "why" comprehension).
- Population norms on our own scale: percentiles are labelled "simulated" until a linking study maps our estimates onto NCPT.
- Languages other than English.
