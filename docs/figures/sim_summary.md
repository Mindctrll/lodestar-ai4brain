# Simulator results (200 users, 10 sessions, seed 2026)

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.818 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.782 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.795 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.644 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.760, after 3: 0.818, after 10: 0.910

| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |
|---|---|---|---|---|
| selective_attention | 0.687 | 0.867 | 0.537 | 100% |
| inhibition | 0.751 | 0.869 | 0.539 | 100% |
| working_memory | 0.831 | 0.915 | 0.415 | 100% |
| short_term_memory | 0.816 | 0.894 | 0.454 | 100% |
| processing_speed | 0.839 | 0.905 | 0.567 | 100% |
| cognitive_flexibility | 0.861 | 0.928 | 0.415 | 100% |
| reasoning | 0.866 | 0.923 | 0.405 | 100% |
| spatial_thinking | 0.853 | 0.943 | 0.370 | 100% |
| numerical_thinking | 0.856 | 0.943 | 0.375 | 100% |

Success in Balanced mode by ability third (low, middle, high): 0.773, 0.799, 0.814 over 4788 rounds.
