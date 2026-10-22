# 13 · Dashboard and UX

> **Reference image:** `design/reference.png`, a light task-manager dashboard: left sidebar, a greeting with the date, a row of stat pills, white cards on a light grey background, one blue accent. This file lists the required content and charts; the layout follows the reference. The dark night-sky Brain Twin sits in that light look as its one dark card.

**As built (WP2.5).** The app is a light shell after the reference: a sidebar (Home, Brain Twin, Progress, Agent, AI collaboration, Settings), the date and greeting, stat pills (day streak, rounds this week, skills measured) and white cards with one blue accent. The night sky is the one dark card, on Home (small) and on the Brain Twin page. It is plain SVG, not visx: each skill's glow is blurred with `feGaussianBlur` in proportion to σ, and dashed lines join skills that NCPT says go together. Charts are ECharts 6 with the SVG renderer: radar with a shaded uncertainty ring, one curve per skill (band, dots per practice day, life-context strips, dashed and hatched forecast band), skill × week and time-of-day × weekday heatmaps (cells under 10 answers left empty), and the ACS gauge with its range on the dial. Every chart lists its series in `data-series`, and the e2e test checks that each estimate has its range. `/twin/stream` pushes `twin_updated` from the scored-round NOTIFY, so every open tab refreshes. The agent page lights up graph nodes from the session's events and lists decisions with their "why" cards and the session trace. `make seed` with `--token` prints a sign-in link for the demo user (`?signin=`, removed from the address bar once used). On a phone the sidebar becomes a top row.

**Redesign (agent first).** The conversation with Lodestar is now the whole app; the dashboard is reached from it. One column holds the greeting, the week pills and the thread. Lodestar's picks show as a dark "ticket" card in the thread, and the game opens wide right there, in the same card. The result card with the coach and the mood buttons follows it. Each turn's `route_intent` reading streams as an `intent` event, and when the turn is answered the UI puts the matching glance in the thread: the night sky for a Twin question, goals for a goal, the lab for an experiment, the week for "how am I doing". Each glance has a way into the full view. The full views (Brain Twin, Progress, Experiments, Agent, AI collaboration, Settings) open from the sidebar as full pages; the conversation stays mounted behind them, so a running game keeps going. The "why" card is a modal. The composer (text, microphone, starter chips) stays at the bottom and hides during a game so keys go to it. Home is centred like a new conversation: a gold star, the greeting, the week pills, two ways in (Start a session, Detective story), then the composer and starter chips. Once the conversation starts, the greeting goes and the thread fills the column. A sidebar on the left holds the views; it folds to icons on narrower screens and becomes a bottom tab bar on phones. A pick is one card: the game's name, one plain sentence on what you do in it, the reason in one muted line with "Why?", and the button. After a round, the card shows the score from the round itself (right out of judged steps), each skill the game moved with its range, any story or encouragement line, and the mood row; the cited fact lines fold under "How I worked this out". While a game runs, the rest of the thread fades back and the game card opens wide, with a progress bar under its header. The type is Bricolage Grotesque for display, Geist for the interface and Geist Mono for labels and numbers. All three are self-hosted, so no font request leaves the device. The theme is a night sky: near-black surfaces, warm off-white text, gold for the star and every primary action, and starlight blue for data. Games play on a light "paper" stage inside the card, so each game's own colours keep their meaning.

## Screens

| Screen | Purpose | Key elements |
|---|---|---|
| Welcome + consent | First run | Plain-language notice, separate switches, persona picker |
| Home | Start here every time | Lodestar orb (tap or "Hey Lodestar"), today's suggestion with its reason, streak, quick resume |
| Game | Play | Shared game frame (`06`), Lodestar's voice line, pause, "too hard?" |
| After-game | Feedback | Coach message with why chips, what changed in the Twin |
| Brain Twin | The profile | Night sky, radar, per-skill pages |
| Progress | History | Curves with bands, heatmaps, goals |
| Agent timeline | Show the agent | Live node graph, decision cards, trace viewer (`03`) |
| ACS | Collaboration | Gauge, components, tips (`11`) |
| Experiments | Personal science | Active and finished experiments, result cards |
| Memory & data | Transparency | `core.md` view and edit, life context, export, delete |
| Settings | Control | Persona, success mode (Chill, Balanced, Push), voice, camera, AI provider (pick one of eight and paste your key, or local mode; the key shows as its last 4 characters only) |

## Required charts (brief: radar, progress curves, heatmaps, goal tracking)

1. **Radar with uncertainty ring:** inner and outer polygons for the 80% range, point estimate as a line. Experimental dimensions dashed.
2. **Progress curves:** one per skill. Line for μ, shaded band for the range, dots for sessions, life-context windows as shaded strips, the Growth Forecast band continuing into the future in a different texture.
3. **Heatmaps:** skill × week (practice volume or change), and time of day × weekday (performance), which feeds experiments.
4. **Goal tracking:** goals like "working memory range down to ±5 by 7 Nov", shown as progress toward the band width, not only the score.
5. **ACS gauge** with range and component bars.

Library: ECharts for these; visx/D3 for the night sky.

## The night sky (Brain Twin visual identity)

- Each dimension is a small constellation; position is fixed so users learn the map.
- **Brightness = μ**, **blur radius = σ** (SVG `feGaussianBlur`, stdDeviation proportional to σ). Stars sharpen as Lodestar learns.
- Stale skills slowly blur (the drift in `07`) and the Twin can say so.
- Lines between constellations show correlated skills.
- Tap a constellation → that skill's page (definition, games, curve, biases, evidence badge).
- Experimental skills shown as faint, dashed constellations with a caption.

## Visual honesty rules

- No number without its range.
- Skills with σ above a threshold are greyed: "still learning about you".
- Forecasts look different from measurements (texture or dashes).
- Simulated norms are labelled.

## UX rules

- Every decision Lodestar makes has a visible "why".
- One primary action per screen.
- Keyboard and touch; works on a phone.
- Captions for everything spoken.
- Reduced-motion setting respected.
- All text in plain English, no clinical words (`09`).
- Loading states never block games: content comes from pools.
