# Spot the AI's Mistake

**Measures:** reasoning (primary), and the AI Collaboration Score's critical verification part
(docs/plan/11): flagging a wrong AI answer and accepting a right one both count, so blanket
distrust doesn't win.

**Paradigm:** original. Lodestar shows a worked solution; most have one subtle planted error
(an arithmetic slip or a wrong operation), confirmed by a solver; the rest are right. The consent
screen tells users Lodestar will sometimes be wrong on purpose.

**What you do:** read the steps. Tap the step that's wrong, or "All steps are right".

**Metrics:** balanced accuracy (mean of right on wrong solutions and right on correct ones).

**Difficulty knobs:** `error_subtlety` 0.2 to 0.9, `steps` 3 to 6.
