# Simulator results (200 users, 10 sessions, seed 2026)

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.820 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.799 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.777 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.649 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.773, after 3: 0.820, after 10: 0.905

| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |
|---|---|---|---|---|
| selective_attention | 0.691 | 0.868 | 0.609 | 100% |
| inhibition | 0.769 | 0.870 | 0.503 | 100% |
| working_memory | 0.824 | 0.907 | 0.436 | 100% |
| short_term_memory | 0.847 | 0.903 | 0.434 | 100% |
| processing_speed | 0.847 | 0.901 | 0.501 | 100% |
| cognitive_flexibility | 0.846 | 0.910 | 0.408 | 100% |
| reasoning | 0.841 | 0.931 | 0.393 | 100% |
| spatial_thinking | 0.849 | 0.933 | 0.379 | 100% |
| numerical_thinking | 0.867 | 0.919 | 0.416 | 100% |

Success in Balanced mode by ability third (low, middle, high): 0.759, 0.778, 0.793 over 4595 rounds.
