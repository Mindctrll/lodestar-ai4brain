# Pattern Gap

**Measures:** reasoning (primary). Also feeds the AI Collaboration Score's autonomy part: hints
are there if you want them, and solving with fewer of them counts (docs/plan/11).

**Paradigm:** matrix reasoning in the style of Raven's progressive matrices; puzzles are
generated from rules (shape, number, fill, rotation; progression or distribution) and a solver
confirms exactly one option fits. Never copied items.

**What you do:** a 3x3 grid has its last cell missing. Pick the option that completes it. Hints
get stronger each time you ask.

**Metrics:** accuracy by number of rules, hints used.

**Difficulty knobs:** `rules` 1 to 4, `distractor_similarity` 0.3 to 0.9.
