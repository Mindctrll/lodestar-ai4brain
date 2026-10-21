# Off Beat

**Measures:** rhythm and timing (experimental, added in the WP4.4 extensibility drill).

**Paradigm:** Anisochrony detection: is a sequence of beats steady, or is the last one displaced? (Ehrlé & Samson, 2005, Brain and Cognition 58, 133-147, https://doi.org/10.1016/j.bandc.2004.09.014; background in Repp, 2005, https://doi.org/10.3758/BF03206433). Written from published descriptions.

**What you do:** a dot blinks with a tick at a steady beat (600 ms). The last beat is either on time or moved early or late. Say which: on the beat (F) or off the beat (J). Half the steps are off.

**Metrics:** `accuracy`, `hit_rate` (off beats noticed), `false_alarm_rate` (steady beats called off). Each step also stores the blink times actually reached (`onsets_ms`), so rounds can be re-scored if the device lagged.

**Difficulty knobs:** `shift_pct` 30 to 6 (how far the last beat moves, in % of the beat), `beats` 6 to 4 (fewer beats to lock on to).
