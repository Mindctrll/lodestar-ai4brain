# 07 · Scoring, uncertainty and difficulty

Goal: for every skill, a score **and** an honest uncertainty, updated after every answer, used to pick the next difficulty.

## Precedent

Math Garden (Klinkenberg, Straatemeier & van der Maas, 2011) ran an Elo system that updated both player and item ratings after every answer, served over 150,000 Dutch children, and scored speed and accuracy together with a "high speed, high stakes" rule. A 2025 paper in *User Modeling and User-Adapted Interaction* adds a dynamic-K Elo, which is the same idea as our "uncertainty grows when you stop practising". We follow that line, with a Kalman/Glicko-style uncertainty.

## The model

Each user has, per dimension *d*, a belief **θ_d ~ Normal(μ, σ²)** on a logit scale. Each game level has a difficulty **b**.

**Predicted success** (accounting for uncertainty):

```
p = logistic( (μ − b) / sqrt(1 + π·σ²/8) )
```

**Observed score S in [0, 1]:**

- Accuracy-only games: S = 1 if correct, else 0.
- Timed games, deadline *d*, response time *t*, correct *x* ∈ {0, 1}, using the high-speed-high-stakes rule:
  `S_raw = (2x − 1) · (1 − t/d)` in [−1, 1], then `S = (S_raw + 1) / 2`.
  Fast and right scores high; fast and wrong scores low; slow answers count little either way. This discourages guessing.
  **As used in the update.** The raw score is shrunk toward 0.5 by slowness, so feeding it into a model of P(correct) pulls μ toward the item and difficulty targeting slides until users succeed almost always; partial credit for slow answers has the same problem in a milder form (simulator coverage fell to 0.65). So the update treats a timed answer as a success when it is right within the reference pace (half the deadline) and a failure otherwise. Fast guesses still cost, and the deadline knob sets the pace a level asks for (`backend/scoring/hshs.py`).
- Span games (Corsi, digit span): one S per sequence.

**Update after each scored response** (one Kalman / Laplace step for a logistic model):

```
w   = loading(game, d) × reliability(game) × context_weight × trust
I   = p · (1 − p)                      # information in this answer
σ²' = 1 / (1/σ² + w · I)               # uncertainty shrinks
μ'  = μ + σ²' · w · (S − p)            # move toward the evidence
```

| Factor | Meaning | Values |
|---|---|---|
| `loading` | How much this game measures this skill | Primary 1.0, secondary 0.3 (from the registry) |
| `reliability` | How much we trust this game type | Classic 1.0; original games 0.8; custom block-built games 0.3–0.5 |
| `context_weight` | Life context ("slept badly", "exam week") | 0.5 inside a flagged window |
| `trust` | Data quality | 0 for flagged random clicking or impossible speed; 1 otherwise |

**Staleness drift** before each session:

```
σ² ← min(σ_start², σ² + q · days_since_practice)
```

q starts at 0.002 per day (σ grows noticeably after about 3 weeks), and we try to fit it to Kumar et al. (2022), who studied relearning after breaks in 39,157 Lumosity users. This is the "blurry star" effect in the Brain Twin.

**Within-session process noise.** Answers in one session aren't independent (the user warms up, tires, learns the task), so treating every trial as fresh evidence makes σ shrink too fast: about 5 answers take σ from 1.5 to 0.8, and 100 answers take it to about 0.2. Before each round we add process noise, `σ² ← σ² + q_round` (q_round = 0.035 after tuning in WP1.2–2.3). WP1.2 tunes `q_round`, `q` and the per-trial weight on the simulator until the 80% ranges contain the true value 75–85% of the time.

**Starting values:** μ = 0 (population average), σ_start = 1.5. The 5-minute onboarding brings the **core skills** (the dimensions the onboarding battery measures with a primary loading) to about σ ≈ 0.8.

## Item and level difficulty

- Each level starts with a designed difficulty from its knobs (for example, n in n-back, set size, angle).
- **Prediction step (as built in the Wave 2 gate):** people improve with practice, which a random walk ignores; through the real graph the estimates lagged the simulated truth by about 0.2 and the 80% ranges held only 74% (now 81%). After each round the mean moves up by the average gain people make at that point, `a·k^-b` per round with a = 0.208 and b = 0.77, fitted to 1.08 million Lumosity learning curves (`registry/practice.yaml`, `make practice-prior`; in 98.6% of that data a session is one play, like one round here). The gain is scaled by loading and trust, so rejected rounds get none, and the next round's answers correct it. `twin.updated` events record a and b, so re-scoring stays exact after a refit.
- Item difficulties are also updated, with a small step and only from users whose σ < 0.6: `b' = b − 0.02 · (S − p)`. Levels drift toward their true difficulty as people play.
- Each game's YAML has a monotonic `level_map` from b to knobs.

## Choosing the next difficulty

Pick the level whose predicted success hits a target p*:

```
b_next = μ − logit(p*)
```

| Mode | p* | Why |
|---|---|---|
| Assess (onboarding, uncertain skills) | 0.60–0.70 | Each answer tells us more near 50–70% |
| Train · Balanced (default) | 0.80 | Wilson et al. (2019) "85% rule"; Math Garden used 0.75 |
| Train · Chill | 0.90 | User wants it relaxing |
| Train · Push | 0.65 | User wants a challenge |

The user chooses Chill, Balanced or Push in settings. Lodestar switches to Assess automatically when σ is high.

**Inside a game,** continuous knobs (presentation time, stop-signal delay) use a staircase: 2-down/1-up converges on 70.7% and 3-down/1-up on 79.4%.

## From scores to percentages (the brief asks for a percentage profile)

- **Percentile** against norms: `P = Φ((μ − m_norm) / s_norm)`.
- **Range** from μ ± 1.28σ, giving an 80% interval: "62% (likely 48–74%)".
- **Norms:** where a dimension maps to an NCPT subtest, we derive norms from the NCPT dataset (757,427 adults, CC BY 4.0). Elsewhere we use simulated norms and say so on screen.
- **As built (WP2.7):** every skill uses simulated norms for now, labelled on screen, because NCPT scores can't be put on our scale without a linking study (`10`). NCPT gives the skill correlations behind cold-start priors: a skill's first round starts from what the measured, correlated skills suggest.
- **Caveat on screen:** norms come from mostly English-speaking online users, so they may not fit Tunisian students. Local pilot data is shown separately.

## Overall score

No headline "brain score". The radar shows each dimension with its range. If a single number is ever shown, it averages Established dimensions only, with its own range.

## Code layout

```
backend/scoring/
  kalman_elo.py      # predict, update, drift; pure functions
  rounds.py          # one round's trials -> updated beliefs (process noise, trust, context)
  hshs.py            # timed scoring
  loadings.py        # registry → loading matrix
  levels.py          # b ↔ knobs, target selection
  staircase.py
  norms.py           # NCPT-derived and simulated norms
  quality.py         # random-clicker and too-fast detection → trust
```

Pure functions with property tests: σ never grows from an answer; μ moves toward S; p* targeting hits within ±5% on the simulator.

## Sources

- Klinkenberg, Straatemeier & van der Maas (2011), Math Garden: https://iranarze.ir/wp-content/uploads/2016/12/E3076.pdf
- Dynamic-K Elo (2025): https://link.springer.com/article/10.1007/s11257-025-09439-z
- Wilson et al. (2019), the 85% rule: https://collaborate.princeton.edu/en/publications/the-eighty-five-percent-rule-for-optimal-learning/
- NCPT dataset: https://zenodo.org/records/7249732
- Kumar et al. (2022), learning and relearning in large-scale cognitive training: https://experts.illinois.edu/en/publications/comparing-models-of-learning-and-relearning-in-large-scale-cognit/
