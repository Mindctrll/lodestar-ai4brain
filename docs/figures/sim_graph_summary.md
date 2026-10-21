# Simulator through the real graph (120 users, 10 sessions, seed 2026)

4239 rounds played through LangGraph, Postgres and the stub coach in 25 minutes. Same experiments and targets as `make sim` (docs/plan/15).

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.830 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.781 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.777 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.607 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.793, after 3: 0.830, after 10: 0.911
