"""Fatigue point, P2 (docs/plan/10, section 3): minutes into a session when this person's answers
usually start to slow down. Behaviour only: response times and errors, never camera or voice.

1. Each answer's response time is compared with the person's usual time for that game (log
   scale, z-score over all their answers to it), so a session that mixes fast and slow games
   still reads as one series.
2. In each past session, a single change to slower answers is looked for: the split that best
   explains the series as "before" and "after" (least squares), kept only if it is clearly
   better than no split (a BIC-style penalty), the "after" part is at least half a standard
   deviation slower, and accuracy didn't improve (that would be care, not fatigue).
3. Across sessions, sessions without a change still count: they say "not before minute m"
   (censored). A Kaplan-Meier curve over all sessions gives the median minute and its middle
   half, so the app shows a range, never one number.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from backend.contracts.twin import FatiguePoint

MIN_TRIALS = 30
MIN_SEGMENT = 10
MIN_EVENTS = 3  # sessions with a change before there is a fatigue point at all
SHIFT_SD = 0.5
PENALTY_PER_PARAM = 1.0  # times log(n): BIC charges log(n) per extra parameter


@dataclass(frozen=True)
class Answer:
    minute: float  # since the session started
    game_id: str
    rt_ms: float
    correct: bool | None


def standardise(sessions: Sequence[Sequence[Answer]]) -> list[np.ndarray]:
    """Log response times as z-scores against the person's usual time for each game."""
    by_game: dict[str, list[float]] = {}
    for session in sessions:
        for a in session:
            by_game.setdefault(a.game_id, []).append(np.log(max(a.rt_ms, 1.0)))
    stats = {g: (float(np.mean(v)), float(np.std(v)) or 1.0) for g, v in by_game.items()}
    out = []
    for session in sessions:
        logs = np.log(np.maximum([a.rt_ms for a in session], 1.0))
        means = np.array([stats[a.game_id][0] for a in session])
        sds = np.array([stats[a.game_id][1] for a in session])
        out.append((logs - means) / sds)
    return out


def changepoint(z: np.ndarray, minutes: np.ndarray, correct: Sequence[bool | None]) -> float | None:
    """The minute of the one clear change to slower answers in a session, or None."""
    n = len(z)
    if n < MIN_TRIALS:
        return None
    total = float(((z - z.mean()) ** 2).sum())
    c1, c2 = np.cumsum(z), np.cumsum(z**2)
    best, best_k = total, -1
    for k in range(MIN_SEGMENT, n - MIN_SEGMENT + 1):
        left = c2[k - 1] - c1[k - 1] ** 2 / k
        right = (c2[-1] - c2[k - 1]) - (c1[-1] - c1[k - 1]) ** 2 / (n - k)
        if left + right < best:
            best, best_k = float(left + right), k
    if best_k < 0 or best <= 0:
        return None
    gain = n * np.log(total / best)  # 2 x the log-likelihood ratio for a mean shift
    if gain < 2 * PENALTY_PER_PARAM * np.log(n):  # two more parameters: the split and the mean
        return None
    sd = np.sqrt(best / (n - 2))
    if (z[best_k:].mean() - z[:best_k].mean()) / sd < SHIFT_SD:
        return None
    marks = [c for c in correct]
    before = [c for c in marks[:best_k] if c is not None]
    after = [c for c in marks[best_k:] if c is not None]
    if before and after and np.mean(after) > np.mean(before) + 0.05:
        return None  # slower but more accurate: taking care, not tiring
    return float(minutes[best_k])


def _km_quantile(times: np.ndarray, events: np.ndarray, survival: float) -> float | None:
    """The first time the Kaplan-Meier curve drops to `survival` or below."""
    order = np.argsort(times)
    times, events = times[order], events[order]
    s = 1.0
    at_risk = len(times)
    for t, e in zip(times, events, strict=True):
        if e:
            s *= 1.0 - 1.0 / at_risk
            if s <= survival:
                return float(t)
        at_risk -= 1
    return None


def fatigue_point(sessions: Sequence[Sequence[Answer]]) -> FatiguePoint | None:
    """The median minute with its middle half, or None until enough sessions show a change."""
    usable = [s for s in sessions if len(s) >= MIN_TRIALS]
    if not usable:
        return None
    times, events = [], []
    for session, z in zip(usable, standardise(usable), strict=True):
        minutes = np.array([a.minute for a in session])
        point = changepoint(z, minutes, [a.correct for a in session])
        times.append(point if point is not None else float(minutes[-1]))
        events.append(point is not None)
    if sum(events) < MIN_EVENTS:
        return None
    t, e = np.array(times), np.array(events)
    median = _km_quantile(t, e, 0.5)
    if median is None:
        return None  # most sessions end before any slowing: no point to plan around
    low = _km_quantile(t, e, 0.75) or median
    high = _km_quantile(t, e, 0.25) or float(t.max())
    return FatiguePoint(
        low=max(low, 0.1),
        median=max(median, 0.1),
        high=max(high, median, 0.1),
        sessions=len(usable),
    )
