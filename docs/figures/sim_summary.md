# Simulator results (200 users, 10 sessions, seed 2026)

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.824 | > 0.8 | yes |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.791 | 0.75-0.85 | yes |
| 3. Achieved success in Balanced mode | 0.796 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.653 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.781, after 3: 0.824, after 10: 0.913

| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |
|---|---|---|---|---|
| selective_attention | 0.808 | 0.895 | 0.462 | 100% |
| inhibition | 0.819 | 0.910 | 0.449 | 100% |
| working_memory | 0.831 | 0.928 | 0.408 | 100% |
| short_term_memory | 0.799 | 0.874 | 0.480 | 100% |
| processing_speed | 0.831 | 0.917 | 0.406 | 100% |
| cognitive_flexibility | 0.852 | 0.933 | 0.397 | 100% |
| reasoning | 0.847 | 0.924 | 0.399 | 100% |
| spatial_thinking | 0.848 | 0.935 | 0.391 | 100% |
| numerical_thinking | 0.784 | 0.902 | 0.411 | 100% |

Success in Balanced mode by ability third (low, middle, high): 0.773, 0.800, 0.816 over 4759 rounds.
