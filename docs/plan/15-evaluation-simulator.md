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
- [ ] Profile rebuilds from the event log
- [ ] LLM-off mode completes a full session
- [ ] Qdrant-off mode completes a full session
- [ ] Refresh during a game resumes correctly
- [ ] Delete removes everything (verified by a script)
- [ ] No API key appears in logs, traces, checkpoints, events or exports (verified with a canary key)

WP4.4 tests this end to end: an agent adds a new dimension and game from scratch using only YAML and one plugin.
