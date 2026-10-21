# 15 · Evaluation and the user simulator

The final round weighs Generalisation 25%, Robustness 25% and Profile quality 20%. We win those with numbers from a simulator where we know each user's true skill.

## The simulator

`simulator/` generates users and plays them through the **real agent graph** (with a stub or local LLM).

Each simulated user has:

- **True skill per dimension**, drawn from a multivariate normal with realistic correlations (0.3–0.5 between executive functions; NCPT factor structure where available).
- **Learning:** power law of practice, `θ(n) = θ0 + g·(1 − (n+1)^(−α))`, with per-game learning rates (hidden, for the bandit test).
- **Forgetting** during gaps.
- **Responses:** P(correct) = logistic(θ − b); response time from a log-normal whose mean falls as θ rises.
- **Nuisance traits:** fatigue slope within a session, lapse rate, device lag.
- **Types:** normal, fast learner, inconsistent, quitter, **random clicker**, **cheater** (impossibly fast and always correct), **frustration-prone**, long gaps.

**As built (Wave 2 gate).**
- **Learning rate:** the simulator's people learn at the Lumosity rate per round (`registry/practice.yaml`) times a personal factor (mean 1, sd 0.35; fast learners 1.6×). The earlier invented gains were about half what real players show.
- **Correlations:** come from NCPT where measured (`registry/priors.yaml`).
- **Through the graph:** `make sim-graph` plays them through the real graph, with days passing between sessions by moving the user's timestamps back, so drift and check-ups see real elapsed time. It checks experiments 1-5 with the same code as `make sim` (`simulator/experiments.py: gate`) and writes `docs/figures/sim_graph_summary.md`.

## Evaluation experiments

| # | Question | Metric | Target |
|---|---|---|---|
| 1 | Does the profile find the true skill? | Correlation and RMSE of μ vs true θ after 1, 3, 10 sessions | r > 0.8 after 3 sessions on Established dimensions |
| 2 | Are the ranges honest? | Share of 80% ranges containing the true value | 75–85% |
| 3 | Does difficulty adapt? | Achieved success rate in Balanced mode across ability levels | 80% ± 5 |
| 4 | Is onboarding enough? | σ after the 5-minute battery | below 0.8 on core skills |
| 5 | Do we catch bad data? | Precision and recall for random clickers and cheaters | > 0.9 / > 0.8 |
| 6 | Robust to gaps and lag? | Recovery error with missing sessions; with 50–150 ms injected lag after calibration | Small degradation, reported |
| 7 | Is the ACS stable? | Rank stability under ±5 weight changes | Spearman ρ > 0.9 |
| 8 | Is the coach faithful? | First-draft and final verifier pass rate | Final 100%, first-draft reported honestly |
| 9 | Does the forecast's range hold? | Interval coverage on held-out Lumosity users | 80% nominal → report observed |
| 10 | Does the bandit help? | Simulated gain vs random game choice | Report the difference |
| 11 | Does the agent degrade gracefully? | Sessions completed with LLM down, Qdrant down | 100% completed |

Each result becomes a plot in `docs/figures/`, produced by `make eval`.

## Real pilot

Once wave 2 is merged: 5–10 consented real users (classmates), 2–3 sessions each. Report separately from simulated results. Collect: usability score (short SUS-style questionnaire), whether "why" cards were understood, and mood-check labels for the frustration detector.

## Robustness checklist

- [ ] New dimension = YAML + docs page; the agent picks it up with no code change
- [ ] New game = plugin + YAML; validated by a simulator run
- [x] Profile rebuilds from the event log
- [x] LLM-off mode completes a full session
- [x] Qdrant-off mode completes a full session
- [x] Refresh during a game resumes correctly
- [x] Delete removes everything (verified by a script)
- [x] No API key appears in logs, traces, checkpoints, events or exports (verified with a canary key)

WP4.4 tests this end to end: an agent adds a new dimension and game from scratch using only YAML and one plugin.

**As built (WP4.1).** Each item and the test that proves it; all run in CI (`make test`, `make sim`).

| Item | Test |
|---|---|
| New dimension / new game from YAML | WP4.4 (extensibility drill) |
| Profile rebuilds from the event log | `tests/backend/db/test_twin_store.py::test_rebuild_gives_identical_projections`; after retention: `tests/backend/ethics/test_data_rights.py::test_retention_drops_old_data_and_keeps_the_profile_rebuildable` |
| LLM-off completes a full session | `tests/backend/agent/test_degradation.py::test_llm_down_completes_a_full_session` (every model call fails; template replies built from facts) |
| Qdrant-off completes a full session | `test_degradation.py::test_qdrant_down_completes_a_full_session` (memory points at a dead port; recall and remember are skipped) |
| Refresh during a game resumes correctly | `test_degradation.py::test_refresh_mid_game_resumes_and_counts_the_replay_once`; also `test_graph.py::test_paused_session_survives_a_server_restart`, `test_duplicate_resume_scores_once`; in the browser `frontend/e2e/uw6.spec.ts` (`make e2e`) |
| Delete removes everything | `tests/backend/ethics/test_data_rights.py::test_delete_leaves_nothing_behind` (finds every `user_id` table from the database itself, plus checkpoints, Qdrant and notes) |
| No API key in logs, traces, checkpoints, events or exports | `tests/backend/agent/test_graph.py::test_canary_key_never_leaks`; exports: `test_data_rights.py::test_export_has_everything_and_never_a_key` |

The rest of WP4.1:
- **Postgres reconnect:** `test_degradation.py::test_postgres_reconnect_mid_session` drops every connection the app holds mid-round. The checkpointer pool now checks each connection before use (`backend/agent/graph.py: checkpoint_pool`); the app engine already pinged.
- **Refresh mid-game** found a bug: the replayed round's trials were counted on top of the unfinished attempt's. Scoring now keeps the latest answer per trial index.
- **Cheat and noise detection:** `backend/scoring/quality.py`, tested in `tests/backend/scoring/test_parts.py` and by experiment 5 in `make sim` (precision and recall gate).
- **Device-latency calibration:** Quick Draw starts with "tap in time" when measuring (onboarding, check-ups); the median tap offset is the device lag (0-250 ms), subtracted from response times before scoring and quality checks, and recorded in `twin.updated` (`ScoringInputs.device_lag_ms`). Tests: `tests/backend/scoring/test_rounds.py::test_device_lag_is_calibrated_and_removed` (50-150 ms injected lag, experiment 6), `test_twin_store.py::test_rounds_are_scored_with_the_calibrated_device_lag`, `frontend/src/games/games.test.ts`. The simulator doesn't inject lag yet; experiment 6 (WP4.2) can use `device_lag()` on simulated taps.
- **Row-level security:** migration 0007 enables RLS on every table with a `user_id`. Per-user transactions (`user_scope()`: API reads and the scored round) switch to the `najma_app` role, which sees and writes only the rows of `app.user_id`. The table owner (migrations, sign-in by token, jobs) is not subject to RLS. Test: `tests/backend/db/test_rls.py`.

**As built (WP4.2).** `make eval` (`simulator/eval.py`) runs all 11 experiments and writes one figure each plus `docs/figures/eval_summary.md`, in about 8 minutes on a busy laptop CPU (6 of them on the coach). It reuses the existing code: experiments 1-5 are `make sim` (200 people; figures `sim_recovery.png`, `sim_success.png`, `eval_02` to `eval_05`); 6 replays the same people with 7-21 days between sessions, or with 50-150 ms of extra device lag from the first session after the warm-up (RMSE after 10 sessions: 0.450 usual, 0.471 with gaps, 0.535 with lag, so lag costs more than gaps); 7 is `backend/acs/sensitivity.py` (worst Spearman 0.997); 8 drafts 4 replies, one per persona, through the coach's draft-verify-repair loop on facts packets from the real `reflect` node, with the local model when Ollama has it (qwen3.5:4b: 0 of 4 first drafts passed, 3 after repair, 1 template, 4 of 4 final), else the stub coach, labelled as such; 9 reads the held-out coverage from the growth forecast's model card (79.7%), since retraining needs the 2.6 GB Lumosity file; 10 is `simulator/bandit.py` at its test size (+0.173 to +0.294 true skill over random games, 95%); 11 plays 6 people x 3 sessions through the real graph with every model failing, Qdrant unreachable, and both, in a throwaway database (`EVAL_DATABASE_URL`, default `najma_eval`): 18 of 18 sessions completed in each case. The real-graph run of 1-5 (`make sim-graph`, about 15 minutes) is opt-in: `make eval GRAPH=120`. `make eval COACH_N=8` drafts more coach replies.
