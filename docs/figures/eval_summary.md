# Evaluation results (`make eval`)

The 12 experiments of docs/plan/15, seed 2026, in 4.8 minutes. Simulated people: 200 for 1-6 and 12 (CI also uses 200), 200 for 7, 200 paired for 10; experiment 11 plays 6 x 3 sessions per condition through the real graph. Status: pass or FAIL against the target; reported where the target is to report a number; skipped when a dependency is missing.

| # | Question | Result | Target | Status | Figure |
|---|---|---|---|---|---|
| 1 | Recovery r after 3 sessions (mean over 9 established skills) | 0.820 (after 1 session: 0.773, after 10: 0.905) | > 0.8 | pass | [sim_recovery.png](sim_recovery.png) |
| 2 | 80% ranges containing the true skill (sessions 3 and 10) | 0.799 | 0.75-0.85 | pass | [eval_02_ranges.png](eval_02_ranges.png) |
| 3 | Achieved success in Balanced mode | 0.777 | 0.8 +/- 0.05 | pass | [sim_success.png](sim_success.png) |
| 4 | Mean sigma after onboarding, worst core skill | 0.649 | < 0.8 | pass | [eval_04_warmup.png](eval_04_warmup.png) |
| 5 | Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | pass | [eval_05_bad_data.png](eval_05_bad_data.png) |
| 6 | Robust to gaps and lag? (RMSE after 10 sessions) | 0.449 usual, 0.479 with gaps (+0.029), 0.535 with lag (+0.085) | Small degradation, reported | reported | [eval_06_gaps_lag.png](eval_06_gaps_lag.png) |
| 7 | Is the ACS stable? (worst of 10 single-weight shifts) | 0.997 (200 simulated people) | Spearman > 0.9 | pass | [eval_07_acs.png](eval_07_acs.png) |
| 8 | Is the coach faithful? (local model qwen3.5:4b, 4 replies, 4 personas) | first draft 3/4, after repair 4/4, template 0/4, final 4/4 | Final 100%, first draft reported | pass | [eval_08_coach.png](eval_08_coach.png) |
| 9 | Does the forecast's range hold? (held-out Lumosity players, from the model card) | 79.7% observed (k=1 to 20: 79.6%-80.0%) | 80% nominal, report observed | reported | [eval_09_forecast.png](eval_09_forecast.png) |
| 10 | Does the bandit help? (200 paired people, prior from 600) | 3.711 random vs 3.943 bandit; difference +0.167 to +0.297 (95%), 74% gained more | Report the difference | reported | [eval_10_bandit.png](eval_10_bandit.png) |
| 11 | Does the agent degrade gracefully? (sessions completed through the real graph), 18 sessions per condition | Every model down: 18/18, Qdrant down: 18/18, Both down: 18/18 | 100% completed | pass | [eval_11_degradation.png](eval_11_degradation.png) |
| 12 | Does the profile hold when answers break the scoring model? (guessing, mixed discrimination, heavy-tailed noise) | r after 3: 0.771 (model-following people: 0.820), after 10: 0.855; 80% ranges hold 0.710 | r after 3 >= 0.75; ranges hold 70-90% | pass | [eval_12_mismatch.png](eval_12_mismatch.png) |

Experiments 1-5 through the real graph are not part of the default run: `make eval GRAPH=120` adds them (about 15 minutes), see [sim_graph_summary.md](sim_graph_summary.md).
