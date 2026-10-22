# Guide the Robot

**Measures:** planning (primary), verbal skill; ACS clarification and iteration.

**Paradigm:** Original game (docs/plan/06, 11).

**What you do:** type instructions such as "up 2, right 3" to take a robot through a maze to the star Lodestar means. Vague instructions (a direction without a number) fail. Some requests are ambiguous (two stars, "the star"): asking Lodestar first is the right move. Up to three tries.

**Metrics:** `optimal_share`, `clarifications`, `retries`. ACS: asking before acting on an ambiguous request, not asking on clear ones (C); a changed retry after a failure that then works (I). Maze and solution are built in code.

**Difficulty knobs:** `maze_size` 4 to 8, `ambiguity` 0 to 0.5 (share of ambiguous requests; at least one per round).
