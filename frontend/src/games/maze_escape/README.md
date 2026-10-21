# Maze Escape

**Measures:** planning (primary), spatial thinking.

**Paradigm:** Maze planning (as in the Porteus mazes and computer maze tasks). Written from published descriptions; mazes are carved depth-first in code.

**What you do:** move from the top-left room to the exit at the bottom right, one room per move. Bumping into a wall isn't a move.

**Metrics:** `extra_moves` (moves beyond the shortest route, on escaped mazes), `planning_time_ms` (time before the first move), `escaped`. Each maze scores `shortest / moves` (0 if not escaped), which is the continuous score the scorer uses.

**Difficulty knobs:** `size` 5 to 15 rooms a side; `dead_ends` 0.1 to 0.5 (share of dead ends kept; the others are opened into loops).
