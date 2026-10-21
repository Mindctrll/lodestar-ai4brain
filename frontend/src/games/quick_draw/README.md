# Quick Draw

**Measures:** processing speed (primary). Also the device-lag baseline at onboarding.

**Device lag (WP4.1):** when measuring (onboarding, check-ups) the round starts with "tap in
time": 10 flashes 600 ms apart, tapped along with like a rhythm game's calibration. Each tap's
offset from its flash is stored as a practice trial; the server takes the median of the latest
taps as the device lag (clamped to 0-250 ms) and subtracts it from every response time it scores
(`backend/scoring/quality.py: device_lag`). Skipped in end-to-end tests.

**Paradigm:** simple and choice reaction time, after the classic Donders/Hick tasks. Written from
published descriptions; no code from PEBL or PsyToolkit.

**What you do:** a star appears in one of 1 to 4 boxes after a short, random wait. Press its key
(Space for one box; D F J K for four) or tap the box.

**Metrics:** median correct RT (ms), accuracy. Answers under 150 ms are anticipations and don't count.

**Difficulty knobs:** `choices` 1 to 4, `deadline_ms` 1500 to 600 (scored with the rescaled
high-speed-high-stakes rule, docs/plan/07).
