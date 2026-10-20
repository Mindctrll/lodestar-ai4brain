"""In-game staircases for continuous knobs (docs/plan/07).

2-down/1-up converges on 70.7% correct; 3-down/1-up on 79.4%.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Staircase:
    value: float
    step: float
    down: int = 2  # correct answers in a row before it gets harder
    lower: float = float("-inf")
    upper: float = float("inf")
    harder_is_lower: bool = True  # e.g. a shorter deadline is harder
    streak: int = 0
    reversals: int = 0
    last_direction: int = 0  # -1 easier, +1 harder

    def respond(self, correct: bool) -> Staircase:
        if correct:
            streak = self.streak + 1
            if streak < self.down:
                return replace(self, streak=streak)
            return self._move(+1)
        return self._move(-1)

    def _move(self, direction: int) -> Staircase:
        sign = -1 if self.harder_is_lower else 1
        value = self.value + sign * direction * self.step
        value = min(max(value, self.lower), self.upper)
        reversal = self.last_direction != 0 and direction != self.last_direction
        return replace(
            self,
            value=value,
            streak=0,
            last_direction=direction,
            reversals=self.reversals + int(reversal),
        )
