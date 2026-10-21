# Custom Game (blocks)

**Measures:** whatever skills the recipe names (`dims`, main skill at 1.0). Each round counts
for those skills at reliability 0.4 (`origin: custom`, docs/plan/07), because a made-up game has
not been tested.

**Paradigm:** none fixed. The user asks for a game ("a game where I remember a phone number
while doing maths"); the LLM writes a recipe from known blocks (docs/plan/08); the server
validates it (`backend/generation/blocks.py`, the source of truth); this engine runs it. Without
a model, a starter recipe is served instead.

**Blocks:** `show_items`, `distractor` (maths true/false or tapping, not scored), `recall`
(ordered, free or recognition), `choice`, `timer`, `rule` (odd/even or high/low, optionally
swapping every N trials), `react` (go/no-go), `feedback`. `engine.ts` turns a recipe into one
timeline item per block per repeat, drawing items from the seed and the pools in `config.yaml`.

**Metrics:** `accuracy` over scored answers (recall positions or items, recognition probes,
choices, rule and react trials), `median_rt_ms` of correct answers.

**Difficulty knobs:** none; the recipe sets timings and lengths (`level_map: none`).
