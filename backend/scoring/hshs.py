"""High-speed, high-stakes scoring for timed games (docs/plan/07, after Math Garden).

Fast and right scores high; fast and wrong scores low; slow answers count little either way,
which discourages guessing.

The raw score is shrunk toward 0.5 by slowness, so it can't be fed straight into a model of
P(correct): the estimate would be pulled toward the item, and difficulty targeting would slide
until users succeed almost always. `hshs_success` rescales it against a reference pace (half the
deadline): correct within the reference pace counts as a full success, wrong within it as a full
failure, and slower answers count partially, down to 0.5 at the deadline.
"""

# Fraction of the deadline that counts as "on pace". Levels set the deadline, so the pace a level
# asks for is part of its difficulty.
REFERENCE_PACE = 0.5


def hshs_score(correct: bool, rt_ms: float, deadline_ms: float) -> float:
    """The raw rule: S = ((2x - 1)(1 - t/d) + 1) / 2, in [0, 1]."""
    if deadline_ms <= 0:
        raise ValueError("deadline must be positive")
    t = min(max(rt_ms, 0.0), deadline_ms)
    raw = (2 * int(correct) - 1) * (1.0 - t / deadline_ms)
    return (raw + 1.0) / 2.0


def hshs_success(
    correct: bool, rt_ms: float, deadline_ms: float, reference_pace: float = REFERENCE_PACE
) -> float:
    """The raw score rescaled to the success scale the Kalman-Elo model predicts."""
    if not 0.0 < reference_pace < 1.0:
        raise ValueError("reference pace must be in (0, 1)")
    s = hshs_score(correct, rt_ms, deadline_ms)
    rescaled = 0.5 + (s - 0.5) / (1.0 - reference_pace)
    return min(max(rescaled, 0.0), 1.0)
