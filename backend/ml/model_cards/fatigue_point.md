# Model card: Fatigue Point

Code: `backend/ml/fatigue.py`. No training data: it is fitted to each person's own sessions when a session starts.

## What it estimates

Minutes into a session when this person's answers usually start to slow down, as a median with its middle half (25th to 75th percentile). The `monitor` node ends a session past the median and says the range: "Your answers usually start to slow down 9 to 14 minutes into a session."

## How

1. Each response time is compared with the person's usual time for that game (log scale, z-score), so sessions that mix fast and slow games read as one series.
2. In each of the last 30 sessions with 30 or more timed answers, one change to slower answers is looked for: the least-squares split into "before" and "after", kept only if it beats no split by a BIC-style penalty, the "after" part is at least half a standard deviation slower, and accuracy didn't go up (slower and more accurate is care, not fatigue).
3. Sessions without a change count as "not before minute m" (censored). A Kaplan-Meier curve over all sessions gives the median and its middle half. There is no estimate until 3 sessions show a change, or if most sessions end before any slowing.

## Checks

`tests/backend/ml/test_more_ml.py`: on synthetic sessions with a known change between minutes 9 and 13 (and two games with different usual speeds), the median lands in that window; calm sessions, short sessions and "slower but more accurate" give no point; calm sessions push the curve later. `tests/backend/agent/test_more_ml_agent.py` runs it through the graph.

## Limits

- Behaviour only: response times and right or wrong answers. It never uses the camera or the voice, and it never writes to the Brain Twin (docs/plan/12, AGENTS.md rule 3).
- Harder levels are slower too; the change test can mistake a run of hard items for slowing. The 0.5 SD threshold and the accuracy check guard against most of it.
- Practice makes people faster over weeks, which shifts the usual time per game.

## Must not be used for

Anything but ending a session at a good moment. It is not a health measure.
