"""High-speed, high-stakes scoring for timed games (docs/plan/07, after Math Garden).

Fast and right scores high; fast and wrong scores low; slow answers count little either way,
which discourages guessing.

The raw score is shrunk toward 0.5 by slowness, so it can't be fed straight into a model of
P(correct): the estimate would be pulled toward the item and difficulty targeting would slide
until users succeed almost always. Partial credit for slow answers has the same problem in a
milder form (simulator coverage fell to 0.65). So for the Kalman-Elo update a timed answer is a
success when it is right within the reference pace (half the deadline), and a failure otherwise.
The deadline knob sets the pace, so the pace a level asks for is part of its difficulty.
"""

# Fraction of the deadline that counts as "on pace".
REFERENCE_PACE = 0.5


def hshs_score(correct: bool, rt_ms: float, deadline_ms: float) -> float:
    """The raw rule: S = ((2x - 1)(1 - t/d) + 1) / 2, in [0, 1]. Reported, not used to update."""
    if deadline_ms <= 0:
        raise ValueError("deadline must be positive")
    t = min(max(rt_ms, 0.0), deadline_ms)
    raw = (2 * int(correct) - 1) * (1.0 - t / deadline_ms)
    return (raw + 1.0) / 2.0


def hshs_success(
    correct: bool, rt_ms: float, deadline_ms: float, reference_pace: float = REFERENCE_PACE
) -> float:
    """1.0 when right within the reference pace, else 0.0: what the model predicts."""
    if not 0.0 < reference_pace < 1.0:
        raise ValueError("reference pace must be in (0, 1)")
    if deadline_ms <= 0:
        raise ValueError("deadline must be positive")
    return 1.0 if correct and rt_ms <= reference_pace * deadline_ms else 0.0
