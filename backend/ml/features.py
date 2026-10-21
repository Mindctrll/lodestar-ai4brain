"""Features for the growth forecast, shared by training and serving so they can't drift apart
(docs/plan/10). Inputs are the first n points of a curve (scores on the population scale and the
sessions between them); the target is the score k sessions later, predicted as a change from the
last score."""

import numpy as np

POWER_C = np.array([0.2, 0.35, 0.5, 0.75, 1.0, 1.5])  # exponents tried for a - b * t^(-c)
FEATURES = [
    "n", "k", "last", "first", "mean", "sd", "lo", "hi", "slope", "curve", "last3", "step",
    "mean_gap", "max_gap", "power_gain", "power_c", "family",
]  # fmt: skip


def power_law(scores: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per row, fit score(t) = a - b * t^(-c) over t = 1..n (best c from a grid, a and b by least
    squares) and extrapolate to t = n + k. Returns (predicted gain over the last score, c)."""
    rows, n = scores.shape
    t = np.arange(1, n + 1, dtype=np.float64)
    best_sse = np.full(rows, np.inf)
    best_pred = np.zeros(rows)
    best_c = np.zeros(rows)
    y = scores.astype(np.float64)
    for c in POWER_C:
        x = -(t**-c)  # score = a + b * x with b >= 0 for a rising curve
        xm = x.mean()
        ym = y.mean(axis=1)
        sxx = ((x - xm) ** 2).sum()
        b = ((x - xm) * (y - ym[:, None])).sum(axis=1) / sxx
        a = ym - b * xm
        sse = ((y - (a[:, None] + b[:, None] * x)) ** 2).sum(axis=1)
        pred = a + b * -((n + k) ** -c)
        better = sse < best_sse
        best_sse = np.where(better, sse, best_sse)
        best_pred = np.where(better, pred, best_pred)
        best_c = np.where(better, c, best_c)
    return best_pred - y[:, -1], best_c


def build(scores: np.ndarray, gaps: np.ndarray, k: np.ndarray, family: np.ndarray) -> np.ndarray:
    """One row per example. `scores` and `gaps` are (rows, n) with the same n for every row."""
    rows, n = scores.shape
    y = scores.astype(np.float64)
    t = np.arange(1, n + 1, dtype=np.float64)
    tc = t - t.mean()
    slope = (y * tc).sum(axis=1) / (tc**2).sum()
    if n >= 3:
        quad = np.polynomial.polynomial.polyfit(t, y.T, 2)  # (3, rows)
        curve = quad[2]
    else:
        curve = np.zeros(rows)
    gain, c = power_law(y, k)
    later = gaps[:, 1:] if n > 1 else np.zeros((rows, 1))
    return np.column_stack(
        [
            np.full(rows, n), k, y[:, -1], y[:, 0], y.mean(axis=1), y.std(axis=1),
            y.min(axis=1), y.max(axis=1), slope, curve, y[:, -3:].mean(axis=1),
            y[:, -1] - y[:, -2] if n > 1 else np.zeros(rows),
            later.mean(axis=1), later.max(axis=1), gain, c, family,
        ]
    ).astype(np.float32)  # fmt: skip
