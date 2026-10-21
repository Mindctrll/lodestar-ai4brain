# Simulator through the real graph (120 users, 10 sessions, seed 2026)

4239 rounds played through LangGraph, Postgres and the stub coach in 13 minutes. Same experiments and targets as `make sim` (docs/plan/15).

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.842 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.795 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.788 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.611 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.801, after 3: 0.842, after 10: 0.908
