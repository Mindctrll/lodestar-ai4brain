# Model card: Best Next Game (bandit)

Code: `backend/ml/bandit.py`; simulator check: `simulator/bandit.py` (`uv run python -m simulator.bandit`). No external data.

## What it does

Gives `plan_next` a `bandit_gain` for each skill (weight 0.10, shown in every decision's breakdown) and picks, within the chosen skill, the game with the best Thompson sample: the game expected to move this person's estimate the most per round, with room to try games we know little about.

## How

- **Reward.** The change in the Brain Twin estimate of the game's main skill, from the `twin.updated` events. A round measures what the person could do when it started, so each change is credited to the game played before it on the same skill.
- **Everyone's prior.** One round's change is mostly measurement noise (about 0.3 logits against 0.02-0.05 of learning). So, for each skill, a least-squares fit across people relates how much their estimate moved after their first round of the skill to how many rounds of each game came before their last one. That gives each game's gain per round and its standard error; a skill needs 30 people with 3 or more rounds of it before its games get a prior. It is recomputed from the latest 50,000 rounds every 10 minutes.
- **Each person.** A normal posterior per (person, game): the prior (with 0.01 for how far a person can differ), updated with the person's credited changes.
- **Choice.** One sample per game; the best wins. Before there is a prior or 10 rounds of the person's own, `bandit_gain` is 0 and the game is picked as before.

## Simulator check (docs/plan/16, WP3.3)

Simulated people get hidden per-game learning rates: an everyone-level rate per game (log-normal, SD 0.4) times a personal one (SD 0.3). 600 people play with random games and build the prior; 200 others then play 30 sessions twice from the same start with the same seeds, once with random games and once with the bandit. Both pick the skill the same way, so only the game differs.

Result (seed 2026): true skill gained per person 3.61 with random games and 3.84 with the bandit; paired difference +0.17 to +0.29 (95% interval); 72% of people gained more. With the person's own rounds alone (no everyone prior), it did not beat random: the signal is too weak, which is why the prior exists.

The seed draws a whole new simulated world (every game's everyone-level rate), so the result was rerun over 13 seeds. The bandit clearly beat random in 9 (lower end of the interval above zero), tied in 2 (5 and 9) and lost in 2 (10: −0.18 to −0.06; 99: −0.16 to −0.04). So it helps on average but not in every world; a likely reason is a world where the games' rates are close together, so the prior's noise costs more than it finds. Each game's rate has its own random stream (keyed by game id), so adding a game to the registry doesn't redraw the others. `tests/simulator/test_bandit_sim.py` runs this check.

## Limits

- The prior is a fit, not an experiment: in the app, people don't get games at random, so a game's estimated gain can carry some of who chooses it. The plan's own variety rules (no game twice in a row, skills chosen by uncertainty) keep the mix broad.
- Gains are on the Brain Twin's scale for the game's main skill; secondary skills a game also trains are not counted.

## Must not be used for

Ranking games for anyone but the policy, or claiming a game "works better" for a person without its range.
