"""Split-conformal calibration (docs/plan/10). With a calibration set the model never saw, the
interval holds the true value at least `coverage` of the time for exchangeable new data.

Two forms:
- around the median: [m - q, m + q], q from |y - m|;
- conformalised quantile regression (Romano et al. 2019): [lo - q, hi + q], q from
  max(lo - y, y - hi). Same guarantee, but the width follows each user's own uncertainty.
"""

import math

import numpy as np


def quantile(scores: np.ndarray, coverage: float) -> float:
    """The finite-sample conformal quantile: the ceil((n + 1) * coverage)-th smallest score."""
    n = len(scores)
    rank = min(n, math.ceil((n + 1) * coverage))
    return float(np.partition(scores, rank - 1)[rank - 1])


def calibrate_median(y: np.ndarray, median: np.ndarray, coverage: float = 0.8) -> float:
    return quantile(np.abs(y - median), coverage)


def calibrate_cqr(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, coverage: float = 0.8) -> float:
    return quantile(np.maximum(lo - y, y - hi), coverage)


def cqr_interval(lo: np.ndarray, hi: np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
    low, high = lo - q, hi + q
    return np.minimum(low, high), np.maximum(low, high)


def coverage(y: np.ndarray, low: np.ndarray, high: np.ndarray) -> float:
    return float(np.mean((y >= low) & (y <= high)))
