# Echo

**Measures:** working memory (primary).

**Paradigm:** the n-back task (Kirchner, 1958), letter version; logic follows published
descriptions (Experiment Factory, jspsych-timelines spatial n-back, both MIT). Our own UI.

**What you do:** letters appear one at a time. Press Space, or tap Match, when the letter is the
same as the one _n_ steps back. Otherwise do nothing.

**Metrics:** hits, false alarms, d-prime (log-linear correction), accuracy. The first _n_ letters
can't be targets and don't count.

**Difficulty knobs:** `n` 1 to 4, `pace_ms` 3000 to 1500.
