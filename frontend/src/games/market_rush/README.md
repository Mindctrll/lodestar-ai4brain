# Market Rush

**Measures:** working memory (primary), short-term memory (0.5).

**Paradigm:** an original game in the spirit of working-memory updating tasks: hold several
orders in mind while some of them change.

**What you do:** customers at a market stall say their orders; some change their minds. Then
fill each customer's basket from memory.

**Metrics:** order accuracy (baskets exactly right), items correct.

**Difficulty knobs:** `customers` 1 to 4, `items_per_order` 2 to 6, `change_rate` 0 to 0.4.
Customer lines are written by the LLM and checked (every item must be named), with plain
template lines as the fallback (docs/plan/08).
