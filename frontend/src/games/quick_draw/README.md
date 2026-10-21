# Quick Draw

**Measures:** processing speed (primary). Also the device-lag baseline at onboarding.

**Paradigm:** simple and choice reaction time, after the classic Donders/Hick tasks. Written from
published descriptions; no code from PEBL or PsyToolkit.

**What you do:** a star appears in one of 1 to 4 boxes after a short, random wait. Press its key
(Space for one box; D F J K for four) or tap the box.

**Metrics:** median correct RT (ms), accuracy. Answers under 150 ms are anticipations and don't count.

**Difficulty knobs:** `choices` 1 to 4, `deadline_ms` 1200 to 450 (scored with the rescaled
high-speed-high-stakes rule, docs/plan/07).
