# 10 · Machine learning models

Two models trained on real public data, plus two light models that need no external data.

## Summary

| Model | Predicts | Data | Phase | Used by |
|---|---|---|---|---|
| **Growth Forecast** | A user's score after the next *k* sessions, as an 80% range | Lumosity learning data (Steyvers & Schafer 2020, OSF) | **P1** | Progress curves, goals, the Twin, bonus "predictive growth" |
| **Engagement Risk** | Chance the user disengages in the next 7 days | OULAD (CC BY 4.0) | P2 | Gentle re-engagement, plan easing |
| Fatigue point | Minutes into a session when performance starts to drop | Our own logs + simulator; optionally Lumosity task-switching trial data | P1 (rules) → P2 (model) | `monitor` node |
| Best next game | Which game gives this user the most expected gain | Online learning (Thompson sampling), no external data | P2 | `plan_next` (`bandit_gain`) |

## 1. Growth Forecast

**Data.** Steyvers & Schafer (2020, *Nature Human Behaviour*): gameplay histories of 36,297 users across 51 tasks, on OSF (https://osf.io/g9zkf/). A download script fetches it; raw data stays out of the repo.

**Task.** Given a user's first *n* sessions on a task (n = 3–10), predict their score at session n + k (k = 5, 10, 20).

**Features.** Scores so far, slope, curvature, variability, days between sessions, longest gap, task id (one-hot or task-level embedding), and the parameters of a fitted power-law curve.

**Models, compared in a notebook:**

1. Baseline: per-user power-law fit `score(n) = a − b·n^(−c)`, extrapolated.
2. LightGBM with quantile loss at 0.1, 0.5 and 0.9.
3. **Split-conformal calibration** on top of the median model (custom ~20 lines or MAPIE), giving 80% intervals with a coverage guarantee on similar data.

**Evaluation.** Hold out users (not sessions). Report MAE of the median, pinball loss, and **observed interval coverage** (for example, "nominal 80%, observed 79%"). That number is our main check that the ranges are honest.

**In the app.** We map our games to the closest Lumosity task family (for example Echo ↔ memory tasks). The curve shows the forecast band, labelled: "Based on patterns from 36,000 players of similar games; personalises as you play." When a user's own history disagrees with the forecast, the user's data wins (Bayesian blend weighted by n).

## 2. Engagement Risk

**Data.** OULAD (Kuzilek et al. 2017, *Scientific Data*): 32,593 students, 10,655,280 daily activity summaries, CC BY 4.0.

**Port only behaviour features** that exist in our app too: days since last activity, activity count trend over 7 and 14 days, recent failures, streak length, session length trend. **No demographics** (fairness).

**Model.** Logistic regression and LightGBM; report AUC and calibration. Labels: withdrawn or no activity in the following window.

**Use.** If risk is high, Najma makes the next session shorter and easier, or sends one friendly nudge. Never guilt, never streak-shaming. The coach can say: "You've played less this week. Want a 3-minute session?"

**Honesty note (shown in the model card):** OULAD is about online courses, not brain games, so this is a transfer of behaviour patterns, validated only on our pilot users.

## 3. Fatigue point

- **P1:** rule. Rolling z-score of RT and error rate against the user's baseline; a sustained rise past 1.5 SD flags fatigue.
- **P2:** changepoint model per user. The estimate becomes the session budget in `monitor`.
- Fatigue is a physical state, outside the EU AI Act's emotion-recognition definition, and it's measured from behaviour only.

## 4. Best next game (bandit)

- Each (user, game) pair keeps a Beta or Gaussian posterior on "μ gain per round".
- Thompson sampling gives `bandit_gain(d)` to the policy (`03`).
- Tested on the simulator, where each simulated user has hidden per-game learning rates.

## NCPT dataset (not a predictor, but important)

NCPT (Jaffe et al. 2022, *Scientific Data*): 757,427 adults, 5.45 million subtest scores, CC BY 4.0, about 329 MB on Zenodo (https://zenodo.org/records/7249732). We use it for:

- **Norms** to turn μ into a percentile (`07`).
- **Cold-start priors:** starting μ for dimensions correlated with ones already measured.
- **Correlation structure** between dimensions, which also makes the simulator realistic.

We never use NCPT demographics to tell a user what to expect based on age or gender.

## Files

```
backend/ml/
  notebooks/01_growth_forecast.ipynb
  notebooks/02_engagement_risk.ipynb
  notebooks/03_ncpt_norms.ipynb
  train_growth.py  train_engagement.py
  conformal.py
  serve.py           # loads the active model files listed in agent.ml_models, exposes predict()
  model_cards/       # one card per model: data, metrics, limits, intended use
```

Every model gets a **model card**: training data, metrics, coverage, limits, what it must not be used for.

## Sources

- Steyvers & Schafer (2020): https://www.nature.com/articles/s41562-020-00935-3 · data https://osf.io/g9zkf/
- NCPT (Jaffe et al. 2022): https://www.nature.com/articles/s41597-022-01872-8 · https://zenodo.org/records/7249732
- OULAD: https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset
