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

**As built (WP2.7).** `make ml-data` downloads `gamedata_preprocessed.csv` (2.6 GB) and `make ml-train` builds one curve per person and game family (one point per session with that family), so "k sessions ahead" means k more sessions with that kind of game. The binned file (`normalized_score_array_*`) has only 8 practice bins per curve, too few for k up to 20. The data has no timestamps, so the gap features count sessions, not days. Scores are scaled per family: 0 is the first-session mean and 1 is the family's spread over all sessions, because some families score on a multiplying scale and their first-session spread is tiny. The 0.1 and 0.9 quantiles are conformalised separately for each k (conformalised quantile regression), so each horizon gets its own coverage guarantee. Results, compared with persistence and the power law, are in `backend/ml/model_cards/growth_forecast.md`. Model files go to `models/` (gitignored, since the OSF project states no licence) and the active model is a row in `agent.ml_models`. In the app, the input is the Brain Twin estimate for each day a skill was practised, mapped to its nearest Lumosity family (`forecast_family` in `registry/dimensions.yaml`). Forecasts appear in coach facts and at `GET /forecast`, always as a range.

## 2. Engagement Risk

**Data.** OULAD (Kuzilek et al. 2017, *Scientific Data*): 32,593 students, 10,655,280 daily activity summaries, CC BY 4.0.

**Port only behaviour features** that exist in our app too: days since last activity, activity count trend over 7 and 14 days, recent failures, streak length, session length trend. **No demographics** (fairness).

**Model.** Logistic regression and LightGBM; report AUC and calibration. Labels: withdrawn or no activity in the following window.

**Use.** If risk is high, Najma makes the next session shorter and easier, or sends one friendly nudge. Never guilt, never streak-shaming. The coach can say: "You've played less this week. Want a 3-minute session?"

**Honesty note (shown in the model card):** OULAD is about online courses, not brain games, so this is a transfer of behaviour patterns, validated only on our pilot users.

**As built (WP3.3).** `make ml-data` also fetches OULAD; `make ml-engagement` builds one example per enrolment and course week (853,000 examples, 25,273 students), labelled "no activity in the next 7 days, or unregistered", with eight behaviour features shared with the app through one function (`backend/ml/engagement.py`; days since last activity, active days in the last 7, the 7 before and the last 28, the trend in activity per active day, the streak, failures in the last 28 days, days since starting). On held-out students: AUC 0.857 for the logistic regression, 0.863 for LightGBM and 0.828 for days-since-last alone, so the regression is served; its numbers live in `agent.ml_models`. Probabilities get an inductive Venn-Abers range (expected calibration error 0.006). In the app the `forecast` node reads it at the start of a session. When even the low end of the range is 0.5 or more, `plan_next` offers a short, easy session: a game of a minute or less, Chill difficulty, two rounds. That takes priority over the post-break check-up. The evidence records the range; the user sees only "A short, easy session today". Card: `backend/ml/model_cards/engagement_risk.md`.

## 3. Fatigue point

- **P1:** rule. Rolling z-score of RT and error rate against the user's baseline; a sustained rise past 1.5 SD flags fatigue.
- **P2:** changepoint model per user. The estimate becomes the session budget in `monitor`.
- Fatigue is a physical state, outside the EU AI Act's emotion-recognition definition, and it's measured from behaviour only.

**As built (WP3.3).** `backend/ml/fatigue.py`: response times as z-scores against the person's usual time per game, one least-squares changepoint per session (kept if it beats a BIC-style penalty, is at least 0.5 SD slower and accuracy didn't rise), and a Kaplan-Meier curve over the last 30 sessions with sessions without a change counted as censored. The median sets `budget.fatigue_point_min`; `monitor` ends the session past it and says the middle half as a range. Card: `backend/ml/model_cards/fatigue_point.md`.

## 4. Best next game (bandit)

- Each (user, game) pair keeps a Beta or Gaussian posterior on "μ gain per round".
- Thompson sampling gives `bandit_gain(d)` to the policy (`03`).
- Tested on the simulator, where each simulated user has hidden per-game learning rates.

**As built (WP3.3).** `backend/ml/bandit.py`. The reward is the change in the Brain Twin estimate of the game's main skill, credited to the game played before it on that skill, since a round measures what was learned earlier. Per-person data alone was too noisy: on the simulator it did not beat random. A population prior fixes this. It is a least-squares fit across people of each skill's total change against rounds of each game, and the person's own rounds update it. With that prior, on the simulator (600 people for the prior, 200 paired), the bandit gains +0.095 to +0.210 more true skill than random game choice (95%), and an oracle gains about +0.21. Card: `backend/ml/model_cards/best_next_game.md`.

## NCPT dataset (not a predictor, but important)

NCPT (Jaffe et al. 2022, *Scientific Data*): 757,427 adults, 5.45 million subtest scores, CC BY 4.0, about 329 MB on Zenodo (https://zenodo.org/records/7249732). We use it for:

- **Norms** to turn μ into a percentile (`07`).
- **Cold-start priors:** starting μ for dimensions correlated with ones already measured.
- **Correlation structure** between dimensions, which also makes the simulator realistic.

We never use NCPT demographics to tell a user what to expect based on age or gender.

**As built (WP2.7).** `make ncpt-priors` computes Spearman correlations between subtests mapped to our skills, across 180,000 test runs in batteries 17 and 32, pooled without demographics. They go to `registry/priors.yaml` and are used for **cold-start priors** (`backend/scoring/priors.py`: a skill's first round starts from the conditional mean given the skills already measured, weighted by how sure those are) and for the simulator's population. They are observed-score correlations, lower than the true skill correlations, which keeps the priors cautious. **Percentiles stay labelled "simulated"**: NCPT norms are in raw subtest units (spans, counts, seconds), and our estimates are on our own game-difficulty scale. Turning one into the other needs a linking study, with the same people playing both. Until then, showing an NCPT percentile would claim an accuracy we don't have.

## Files

```
backend/ml/
  notebooks/01_growth_forecast.ipynb
  notebooks/02_engagement_risk.ipynb
  notebooks/03_ncpt_norms.ipynb
  train_growth.py  train_engagement.py
  engagement.py  fatigue.py  bandit.py
  conformal.py
  serve.py           # loads the active model files listed in agent.ml_models, exposes predict()
  model_cards/       # one card per model: data, metrics, limits, intended use
```

Every model gets a **model card**: training data, metrics, coverage, limits, what it must not be used for.

## Sources

- Steyvers & Schafer (2020): https://www.nature.com/articles/s41562-020-00935-3 · data https://osf.io/g9zkf/
- NCPT (Jaffe et al. 2022): https://www.nature.com/articles/s41597-022-01872-8 · https://zenodo.org/records/7249732
- OULAD: https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset
