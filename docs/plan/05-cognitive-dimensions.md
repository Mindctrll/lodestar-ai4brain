# 05 · Cognitive dimensions

The brief refers to a list of cognitive dimensions that isn't in the PDF, so this is our list. Changing it is a YAML edit in the registry.

## Where the list comes from

We built the list from four well-known frameworks, so every dimension can be defended:

- **CHC theory** (Cattell–Horn–Carroll): broad abilities such as fluid reasoning, working memory, processing speed, visual processing, quantitative knowledge and comprehension-knowledge.
- **Miyake et al. (2000)**: three core executive functions, updating (working memory), shifting (flexibility) and inhibition. They're related but distinct.
- **NIH Toolbox Cognition Battery**: standard non-clinical task-to-domain pairs (Flanker, card sort, list sorting, picture sequence memory, pattern comparison).
- **NCPT (Lumos Labs)**: a large web battery whose domains (working memory, visuospatial memory, psychomotor speed, reasoning, inhibition, numerical calculation, selective and divided attention) map almost one-to-one onto ours.

Check exact citations before they go into the docs.

## Evidence badges

Every dimension shows a badge in the UI and the docs:

- **Established:** strong construct, standard tasks, usable reliability.
- **Moderate:** real construct, but measurement is noisier or more strategy-dependent.
- **Experimental:** shown with wide bands and a caption, and **excluded from any overall score**.

## The 16 dimensions

| # | Dimension | Plain meaning | Main tasks | Main metric | Watch out for | Badge |
|---|---|---|---|---|---|---|
| 1 | Selective attention | Focusing on what matters | Flanker, visual search, Posner cueing | Flanker RT cost; search slope (ms/item) | Screen size, device lag, speed vs accuracy | Established |
| 2 | Sustained attention | Staying alert over time | Night Guard (vigilance), SART-style | Hits, false alarms, d′, RT variability | Boredom, noisy room | Established |
| 3 | Divided attention | Doing two things at once | Dual task, Control Tower | Dual-task cost (% drop vs single) | Strategy learning | Moderate |
| 4 | Inhibition | Holding back an automatic response | Stroop, go/no-go, stop-signal | Stroop effect, commission errors, SSRT | Reading fluency (English colour words) | Established |
| 5 | Working memory | Holding and using information | N-back, backward digit span, operation span, Souk Rush | d′ by n, span | Chunking strategies, n-back practice gains | Established |
| 6 | Short-term memory | Remembering what you just saw | Word recall, picture recognition, delayed recall | Items recalled, recognition d′ | Language, repeated lists (use fresh content) | Established |
| 7 | Processing speed | Speed on simple tasks | Simple/choice RT, symbol matching, pattern comparison | Median RT, items/min | Device latency, motor speed | Established |
| 8 | Cognitive flexibility | Switching rules | Task switching, trail switching, Secret Rules card sort | Switch cost, perseverative errors | Card sort loses meaning on repeat once the trick is known | Established |
| 9 | Planning | Thinking ahead | Tower of London, mazes, Guide the Robot | % optimal solutions, planning time, extra moves | Trial-and-error strategies | Moderate |
| 10 | Reasoning | Logic and patterns | Matrices, logic puzzles, Spot the AI's Mistake | Accuracy by item difficulty | Item memorisation (generate fresh, solver-check) | Established |
| 11 | Spatial thinking | Imagining shapes | Mental rotation, paper folding, Corsi blocks | Angle–RT slope, accuracy, span | Prior gaming experience | Established |
| 12 | Verbal skill | Working with words | Word fluency, anagrams, Teach Me | Words/min, solutions | **English-only rule disadvantages Arabic/French speakers** | Moderate (flag the language issue) |
| 13 | Numerical thinking | Feel for numbers | Number line, estimation, fast arithmetic | % absolute error, RT | Maths anxiety, schooling | Established |
| 14 | Decision style under risk | Cautious ↔ bold | Balloon pump (BART-style), card gamble (IGT-style) | Adjusted pumps, advantageous choices | Learning the task vs risk preference | Moderate; **shown as a style, not better/worse** |
| 15 | Self-awareness of accuracy | Knowing when you're right | "How sure are you?" after some answers, across games | Calibration error, Brier score | Needs many answers; linked to accuracy | Experimental |
| 16 | Creativity | Generating ideas | Unusual Uses, LLM-rated | Fluency, originality | LLM rater bias; validity unproven | Experimental, **not in any overall score** |

## The reliability trap

Classic tasks are built to show group effects, not to rank individuals. Hedge, Powell & Sumner (2018) found test-retest reliability from about 0 to .82 across seven classic tasks; the Stroop RT cost reached only about .6. Our response:

1. Score each dimension from **several tasks**, not one.
2. Use **Bayesian estimates with uncertainty** instead of raw difference scores (reanalyses with hierarchical models show higher reliability).
3. **Always show the range**, and never rank people on a single difference score.

## Scoring rules for every reaction-time task

- Drop anticipations (under 150–200 ms) and lapses (over the task deadline); log how many were dropped.
- Use median RT and an accuracy-plus-speed score (see `07`).
- Store raw trials, so we can re-score later.
- At onboarding, measure a simple-RT baseline to estimate device lag, and use it as a correction.

## What each dimension's doc must contain (brief requirement)

`docs/dimensions/<dim>.md`, generated from the registry and filled in by hand:

1. **Definition** in plain words.
2. **Tasks** that measure it, with weights.
3. **Scoring:** metrics, cleaning rules, how they become the dimension score.
4. **Uncertainty:** how σ is computed, what widens it, typical number of rounds to reach ±10.
5. **Biases and confounds:** language, device, practice, culture.
6. **Evidence badge** and sources.

**As built (WP4.3).** `make docs` (`backend/docs_gen.py`) writes one page per dimension to `docs/generated/dimensions/<id>.md`, plus `acs.md`, `data-policy.md`, `model-cards.md` and a `README.md` index, all from the registry and code constants (loadings, reliabilities, cleaning thresholds, σ settings, ACS weights, consent switches, retention periods). Nothing is filled in by hand: a page that needs more text gets it from the registry. The generator stops and lists every missing field (a dimension with no sources, a game with no paradigm, a model card without "Limits" or "Must not be used for"), and `tests/backend/test_docs_gen.py` fails if a page is out of date, so a new dimension needs `make docs` in the same change. `make lint-language` scans the generated pages. Every dimension now cites checked sources (DOIs resolved through Crossref). One finding from the code: with the per-round process noise, practice alone can't bring the 80% range below about ±19 points in the middle of the scale, so the "rounds to reach ±10" asked for above isn't reachable; the pages say how many rounds reach ±20 and where the floor is.

## Registry format

Which games measure a dimension, and how strongly, is written once, in each game's file (`dims: {working_memory: 1.0, short_term_memory: 0.5}`, see `06`). The loader derives each dimension's task list from there, so the two can't disagree.

```yaml
# registry/dimensions.yaml
- id: working_memory
  name: Working memory
  plain: Holding information in mind and using it
  badge: established
  in_overall: true
  group: memory                  # where its constellation sits in the night sky
  framework: [CHC:Gwm, Miyake:updating, NIH:list_sorting, NCPT:working_memory]
  main_metric: d-prime by n, span
  biases: [chunking strategy, practice gains on n-back]
  sources:
    - https://www.nature.com/articles/s41597-022-01872-8
```
