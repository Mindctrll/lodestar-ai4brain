# 11 · AI Collaboration Score (ACS)

The ACS measures **how well the user works with the AI**, from 0 to 100. It's computed from what users do, not from self-report or simple counters.

## Components and how we measure them

| Code | Component | Measured in | Success | Opportunity |
|---|---|---|---|---|
| **V** | Critical verification | Spot the AI's Mistake; disclosed wrong hints (20–30% of hints in some games); the "check" button | Correctly flagging a wrong AI output **or** correctly accepting a right one (balanced accuracy, so blanket distrust doesn't win) | Every AI output the user must accept or reject |
| **A** | Autonomy | Hint ladder in all games; "attempt before asking" | Solving with fewer hints; trying before asking | Every item where hints are available |
| **I** | Iteration | Guide the Robot, Teach Me, failed rounds | A *changed* retry after a failure (new strategy or edited instruction), weighted by whether it improved | Every failed or partial attempt |
| **C** | Clarification | Guide the Robot and Teach Me include deliberately ambiguous moments | Asking a clarifying question before acting on something ambiguous; not over-asking on clear things | Every ambiguous moment (and clear ones as controls) |
| **R** | Responsible use | Session behaviour and settings | Taking suggested breaks, not trying to extract answers in assessment mode, respecting low-confidence warnings | Every relevant prompt or event |

All of this is disclosed in the consent screen ("Najma will sometimes be wrong on purpose to see whether you check").

## Formula

Each component is a Beta posterior with a Beta(2, 2) prior, so a new user starts at 0.5 with wide uncertainty:

```
s_k = (successes_k + 2) / (opportunities_k + 4)

ACS = 100 × Σ_k w_k · s_k
```

The range comes from 1,000 Monte Carlo draws from the five Beta posteriors (80% interval). A component with fewer than 5 opportunities shows "not enough data", and its weight is spread proportionally over the others.

## Weights

| | Brief's proposal | **Ours** | Why |
|---|---|---|---|
| Critical verification | 25 | **30** | Lee et al. (CHI 2025, 319 knowledge workers) found that the more people trust GenAI, the less critical thinking they do, and that critical thinking with AI shifts toward verification. Buçinca et al. (2021) showed over-reliance on AI is the main failure mode and persists even with explanations. |
| Autonomy | 20 | 20 | — |
| Iteration | 20 | 20 | — |
| Clarification | 20 | **15** | Opportunities are the rarest, so this estimate is the noisiest. |
| Responsible use | 15 | 15 | — |

We present the weights as a **design hypothesis**, like the brief does. Validation: on the simulator, rank stability of users under ±5-point weight changes (Spearman ρ), and the share of users whose ACS range overlaps under each weighting.

## Dashboard

A gauge with the 80% range, five bars for the components (each with its range and opportunity count), and tips: "You accepted 3 of 4 wrong hints today. Try the check button before accepting."

## Code

```
backend/acs/
  events.py      # AcsEvent types emitted by games and the agent
  score.py       # Beta posteriors, weights, Monte Carlo interval
  sensitivity.py # simulator sensitivity analysis
```

## Sources

- Buçinca, Malaya & Gajos (2021), cognitive forcing and over-reliance: https://www.eecs.harvard.edu/~kgajos/papers/2021/bucinca21trust.pdf
- Lee et al. (CHI 2025), GenAI and critical thinking (summary): https://sites.psu.edu/digitalshred/2025/03/17/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers-lee-et-al/
