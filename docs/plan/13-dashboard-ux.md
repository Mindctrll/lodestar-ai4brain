# 13 · Dashboard and UX

> **Reference image:** `design/reference.png`, a light task-manager dashboard: left sidebar, a greeting with the date, a row of stat pills, white cards on a light grey background, one blue accent. This file lists the required content and charts; the layout follows the reference. Open question (`17`): how the dark night-sky Brain Twin fits that light look.

## Screens

| Screen | Purpose | Key elements |
|---|---|---|
| Welcome + consent | First run | Plain-language notice, separate switches, persona picker |
| Home | Start here every time | Najma orb (tap or "Hey Najma"), today's suggestion with its reason, streak, quick resume |
| Game | Play | Shared game frame (`06`), Najma's voice line, pause, "too hard?" |
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
- **Brightness = μ**, **blur radius = σ** (SVG `feGaussianBlur`, stdDeviation proportional to σ). Stars sharpen as Najma learns.
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

- Every decision Najma makes has a visible "why".
- One primary action per screen.
- Keyboard and touch; works on a phone.
- Captions for everything spoken.
- Reduced-motion setting respected.
- All text in plain English, no clinical words (`09`).
- Loading states never block games: content comes from pools.
