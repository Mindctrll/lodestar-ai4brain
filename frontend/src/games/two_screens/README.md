# Two Screens

**Measures:** divided attention.

**Paradigm:** Dual task (Pashler, 1994): a simple question task done alone and while tracking a moving dot. Written from published descriptions.

**What you do:** answer yes-or-no questions ("Is 14 an even number?"). On half the steps a dot drifts along a bar at the same time, and you keep it in the middle band with the arrows.

**Metrics:** `dual_task_cost` (median answer time while tracking minus median answer time alone, right answers only), `accuracy`, `on_target` (share of time the dot stayed in the band).

**Difficulty knobs:** `dot_speed` 0.5 to 2.0; `question_rate` 0.1 to 0.4 questions per second while tracking (more means less tracking time before each question, capped at 4 s in config.yaml).
