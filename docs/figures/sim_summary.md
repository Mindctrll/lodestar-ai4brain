# Simulator results (200 users, 10 sessions, seed 2026)

| Experiment | Result | Target | Pass |
|---|---|---|---|
| 1. Recovery r after 3 sessions (mean over 9 established skills) | 0.728 | > 0.8 | NO |
| 2. 80% ranges containing the true skill (sessions 3 and 10) | 0.652 | 0.75-0.85 | NO |
| 3. Achieved success in Balanced mode | 0.792 | 0.8 +/- 0.05 | yes |
| 4. Mean sigma after onboarding, worst core skill | 0.687 | < 0.8 | yes |
| 5. Bad-data detection precision / recall | 1.00 / 1.00 | > 0.9 / > 0.8 | yes |

Recovery r by session: after 1: 0.648, after 3: 0.728, after 10: 0.870

| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |
|---|---|---|---|---|
| selective_attention | 0.507 | 0.775 | 1.000 | 100% |
| inhibition | 0.578 | 0.796 | 0.868 | 100% |
| working_memory | 0.810 | 0.917 | 0.441 | 100% |
| short_term_memory | 0.805 | 0.909 | 0.420 | 100% |
| processing_speed | 0.599 | 0.758 | 1.358 | 100% |
| cognitive_flexibility | 0.817 | 0.915 | 0.435 | 100% |
| reasoning | 0.830 | 0.919 | 0.423 | 100% |
| spatial_thinking | 0.837 | 0.938 | 0.388 | 100% |
| numerical_thinking | 0.769 | 0.898 | 0.422 | 100% |

Success in Balanced mode by ability third (low, middle, high): 0.767, 0.791, 0.820 over 4784 rounds.
