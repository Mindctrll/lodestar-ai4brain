# Simulator results (200 users, 10 sessions, seed 2026)

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.816 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.791 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.776 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.645 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.757, after 3: 0.816, after 10: 0.908

| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |
|---|---|---|---|---|
| selective_attention | 0.683 | 0.869 | 0.483 | 100% |
| inhibition | 0.739 | 0.886 | 0.470 | 100% |
| working_memory | 0.833 | 0.894 | 0.456 | 100% |
| short_term_memory | 0.811 | 0.887 | 0.469 | 100% |
| processing_speed | 0.844 | 0.915 | 0.501 | 100% |
| cognitive_flexibility | 0.844 | 0.931 | 0.401 | 100% |
| reasoning | 0.847 | 0.926 | 0.395 | 100% |
| spatial_thinking | 0.875 | 0.936 | 0.384 | 100% |
| numerical_thinking | 0.873 | 0.927 | 0.421 | 100% |

Success in Balanced mode by ability third (low, middle, high): 0.760, 0.776, 0.791 over 4792 rounds.
