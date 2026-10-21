# Unusual Uses

**Measures:** creativity (experimental: shown with its badge, never in an overall score).

**Paradigm:** Alternative Uses Task (Guilford, 1967). Written from published descriptions.

**What you do:** for each of two everyday objects (a brick, a spoon, a shoe...), list as many different uses as you can in 90 seconds.

**Metrics:** `fluency` (different ideas), `originality` (ideas that use none of the object's everyday-use words, listed in config.yaml). Each object scores `(fluency + originality) / 12`, capped at 1, as a rubric score at the game's low weight (registry reliability 0.5). Originality is scored in code for now; the plan's AI rating can replace it (the ideas are kept in each trial's response for that).

**Difficulty knobs:** none.
