# 06 · Games catalog

Every game is a jsPsych 8.3 plugin (or timeline) with our own UI. Classic tests are **recreated from published descriptions**, never copied from PEBL or PsyToolkit code.

## Where code may come from

| Source | Licence | Use |
|---|---|---|
| jsPsych core + official plugins | MIT | Use directly |
| `jspsych/jspsych-timelines` | MIT | Starting points: arrow flanker, BART, go/no-go, Posner cueing, spatial n-back, Columbia card |
| Experiment Factory task repos | MIT / BSD-3 | Port the logic (written for jsPsych 5/6): Stroop, flanker, n-back, stop-signal, choice RT |
| `jspsych-contrib` | **Check each package** | Corsi blocks, Tower of London, spatial grid |
| `jspsych-psychophysics` | MIT | Precise timed stimuli |
| PEBL | GPL-2.0 | **Ideas only.** Read test descriptions and parameters, cite Mueller & Piper (2014) |
| PsyToolkit | GPL-3.0 / CC BY-NC-SA | **Ideas only** |

Keep a `THIRD_PARTY.md` entry for any MIT/BSD code reused.

## Shared game rules

- 1–3 minutes per game, with a 3-trial practice the first time.
- Same frame for all games: header (game name, skill chips, round progress), stage, footer (pause, "too hard?", quit).
- Instructions shown on screen and optionally spoken by the persona voice.
- Every trial emits: `trial_id`, `game_id`, `level`, `stimulus`, `response`, `correct`, `rt_ms`, `hint_level`, `confidence` (if asked), `ts`.
- Difficulty is set by "knobs" listed in the game's YAML; the scorer maps level → knobs (`07`).
- Keyboard and touch both work; no colour-only cues (shape or label as well), except where colour is the task (Stroop has a colour-blind mode using patterns).

## Catalog

Phase = build group (see `16`): **P1** = core set, built in waves 1–2 (WP1.3, WP2.1); **P2** = wave 3 (WP3.1); **L** = late games, wave 3 (WP3.10, after WP3.1).

### Attention and inhibition

| Game | Skill(s) | What you do | Metrics | Difficulty knobs | Origin | Phase |
|---|---|---|---|---|---|---|
| Ink Clash (Stroop) | Inhibition | Tap the ink colour, not the word | Stroop effect, accuracy | Time limit, % mismatched, response mapping | Classic; ExpFactory logic | **P1** |
| Arrow Storm (Flanker) | Selective attention, inhibition | Which way does the middle arrow point? | Flanker cost, accuracy | Deadline, % incongruent, distractor count | jspsych-timelines | **P1** |
| Odd One Out (visual search) | Selective attention | Find the different item in a crowd | Search slope | Set size, similarity | Classic | **P1** |
| Hold It (go/no-go) | Inhibition | Tap for most shapes, hold for one | Commission errors, RT | Go ratio, pace | jspsych-timelines | **P1** |
| Brake (stop-signal) | Inhibition | Respond, but stop when a beep sounds | SSRT | Staircased stop delay | ExpFactory logic | P2 |
| Look Here (Posner cueing) | Selective attention | React where a hint points, or doesn't | Cue validity effect | Cue validity, timing | jspsych-timelines | P2 |
| Night Guard (vigilance) | Sustained attention | Press only for rare signals over 3 minutes | Hits, false alarms, d′, RT drift | Rarity, duration, signal subtlety | Classic CPT (PEBL has variants) | P2 |
| Control Tower | Divided attention | Land planes while rules change | Dual-task cost | Planes, rule-change rate | **Original** | P2 |
| Two Screens (dual task) | Divided attention | Track a dot while answering questions | Dual-task cost | Speed, question rate | Classic | L |

### Memory

| Game | Skill(s) | What you do | Metrics | Knobs | Origin | Phase |
|---|---|---|---|---|---|---|
| Echo (n-back) | Working memory | Does this match the one *n* steps back? | d′ by n | n, pace | Classic; ExpFactory / timelines | **P1** |
| Souk Rush | Working memory, short-term memory | Fill market orders from memory; customers change their minds | Items correct, order accuracy | Customers, items per order, changes | **Original** | **P1** |
| Light Path (Corsi) | Spatial thinking, working memory | Tap squares in the order they lit (or backwards) | Span | Sequence length, speed, backwards | Classic (check contrib licence) | **P1** |
| Digits Back | Working memory | Hear or see digits, type them backwards | Span | Length, speed | Classic | P2 |
| Sum & Keep (operation span) | Working memory | Solve sums while remembering letters | Span, maths accuracy | Set size | Classic | L |
| Market List (word recall) | Short-term memory | Words flash; type all you remember | Items recalled | Length, speed | Classic (prototype exists) | **P1** |
| Seen It? (picture recognition) | Short-term memory | Old picture or new? | Recognition d′ | Set size, similarity | Classic | P2 |
| Callback (delayed recall) | Short-term memory | At the end of the session, recall the earlier list | Delayed recall % | Delay | Classic | P2 |
| Name Tags | Short-term memory | Match drawn characters to names | Accuracy | Pairs | Classic (drawn characters only, never real faces) | L |

### Speed

| Game | Skill(s) | What you do | Metrics | Knobs | Origin | Phase |
|---|---|---|---|---|---|---|
| Quick Draw (simple/choice RT) | Processing speed | Tap as soon as the target appears (1 or 4 choices) | Median RT | Choices | Classic; also the device-lag baseline | **P1** |
| Symbol Code (digit-symbol) | Processing speed | Match symbols to a key, fast | Items/min | Key size, time | Classic (PEBL has one) | **P1** |
| Twins (pattern comparison) | Processing speed | Same or different? | Items/min, accuracy | Complexity | Classic | P2 |
| Connect (trail A) | Processing speed | Join 1→25 in order | Time | Count, layout | Classic | P2 |

### Flexibility and planning

| Game | Skill(s) | What you do | Metrics | Knobs | Origin | Phase |
|---|---|---|---|---|---|---|
| Switch (task switching) | Flexibility | Sort by colour or by shape, as the cue says | Switch cost | Switch rate, cue time | Classic | **P1** |
| Secret Rules (card sort) | Flexibility | Sort artifacts; the rule secretly changes | Perseverative errors | Rules, change frequency | Classic WCST idea; **original theme** | P2 |
| Zigzag (trail B) | Flexibility | Join 1→A→2→B… | B − A time | Count | Classic | P2 |
| Tower (Tower of London) | Planning | Match the picture in the fewest moves | % optimal, planning time | Minimum moves | Classic (check contrib licence) | P2 |
| Maze Escape | Planning | Find the exit | Extra moves, planning time | Size, dead ends | Classic | L |
| Guide the Robot | Planning + ACS (clarification, iteration) | Type instructions to move a robot; vague ones fail | Optimal %, clarifications, retries | Maze size, ambiguity | **Original** | P2 |

### Reasoning, spatial, verbal, numbers

| Game | Skill(s) | What you do | Metrics | Knobs | Origin | Phase |
|---|---|---|---|---|---|---|
| Pattern Gap (matrices) | Reasoning | What completes the pattern? | Accuracy by item difficulty | Rules per item | Classic; **LLM + solver-generated** | **P1** |
| Spot the AI's Mistake | Reasoning + ACS (verification) | Najma solves a puzzle; find the planted error, or confirm it's correct | Balanced accuracy | Error subtlety, % correct items | **Original** | **P1** |
| Logic Lock | Reasoning | If-then puzzles | Accuracy | Premises | Classic | P2 |
| Detective (story mode) | Reasoning + several | A mystery where each chapter is a game | Per-game metrics | — | **Original** | L |
| Turn It (mental rotation) | Spatial | Same shape or mirrored? | Angle–RT slope | Angle, 2D/3D | Classic | **P1** |
| Fold & Punch | Spatial | Where do the holes end up? | Accuracy | Folds | Classic | L |
| Word Burst (fluency) | Verbal | Words starting with a letter in 60s | Valid words/min | Letter, time | Classic | P2 |
| Scramble (anagrams) | Verbal | Unscramble words | Solved, time | Length | Classic | P2 |
| Teach Me | Verbal, reasoning + ACS (clarification) | Explain something to a confused Najma | Rubric score (LLM-rated, low weight) | Topic difficulty | **Original** | P2 |
| Number Line | Numerical | Place a number on a line | % absolute error | Range | Classic | **P1** |
| Which Jar? (estimation) | Numerical | Which side has more? | Accuracy, RT | Ratio | Classic | P2 |
| Quick Maths | Numerical | Fast arithmetic | Correct/min | Operations, size | Classic | P2 |

### Style and experimental

| Game | Skill(s) | What you do | Metrics | Origin | Phase |
|---|---|---|---|---|---|
| Balloon Pump | Decision style | Pump for points; the balloon may pop | Adjusted pumps (shown as a style) | jspsych-timelines BART | P2 |
| Card Gamble | Decision style | Pick from 4 decks; learn which pay off | Advantageous choices | IGT idea (PEBL has one) | L |
| "How sure are you?" | Self-awareness of accuracy | A confidence slider after some answers in any game | Calibration error | Classic metacognition | P2 |
| Unusual Uses | Creativity (experimental) | List uses for an everyday object | Fluency, LLM-rated originality | Classic AUT | L |

## Core set (15 P1 games, covering every Established dimension except sustained attention)

Quick Draw, Ink Clash, Arrow Storm, Odd One Out, Hold It, Echo, Light Path, Market List, Souk Rush, Symbol Code, Switch, Pattern Gap, Spot the AI's Mistake, Turn It, Number Line.

Night Guard (sustained attention) is a P2 game because a good vigilance test needs about 3 minutes, which is too long for the onboarding battery.

## Game YAML

```yaml
# registry/games/souk_rush.yaml
id: souk_rush
name: Souk Rush
dims: {working_memory: 1.0, short_term_memory: 0.5}
origin: original
licence_notes: none
duration_s: 120
metrics: [items_correct, order_accuracy]
knobs:
  customers: {min: 1, max: 4}
  items_per_order: {min: 2, max: 6}
  change_rate: {min: 0.0, max: 0.4}
level_map: generated            # scorer maps level 0..1 → knobs
content: llm                    # items and customer lines generated, see 08
acs_hooks: []
```
