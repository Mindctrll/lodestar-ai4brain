# TaskHost: how games run in the browser

`TaskHost` mounts one game's jsPsych timeline, streams every trial to `POST /api/events` in small
batches (`TrialBatcher`, with retries), and reports a `RoundResult` when the round ends. The agent
then resumes the paused graph with that result (docs/plan/02, "Main data flow").

`GameFrame` wraps it in the frame every game shares: name, skill chips, progress, and the Pause,
Too hard? and Quit buttons (docs/plan/06, "Shared game rules").

## Adding a game

1. Register it first: `registry/games/<game-id>.yaml` (dimensions and loadings, knobs from easy to
   hard, scoring rule). Leave `available: false` until the plugin works.
2. Create `src/games/<game-id>/` with:
   - `plugin.ts`: build items from the spec's knobs with the seeded `rng`, make the plugin with
     `makePlugin`, and export `game: GameModule` (`timeline`, `metrics`, instructions, keys hint).
     When `e2e` is true, set `stage.dataset.answer` to the expected answer so Playwright can play it.
   - `config.yaml`: browser-side settings (keys, colours, trial counts), imported with `?raw`.
   - `README.md`: paradigm source and citation, metrics, difficulty knobs.
3. Add it to `src/games/index.ts` and set `available: true` in the registry.
   `src/games/registry.test.ts` checks the two lists match.
4. Tests: a hand-calculated fixture for `metrics`, and a Playwright run in `e2e/games.spec.ts`.

## What every trial records

`trial_index`, `practice`, `stimulus`, `response`, `correct` (`null` when there is no right answer),
`rt_ms` (from the moment the stimulus was painted, `performance.now()`), plus the round, session,
game, level and timestamp added by `TaskHost`. Keyboard and touch both work, and no game relies on
colour alone unless colour is the task.
