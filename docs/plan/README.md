# AI4Brain: Najma, the Cognitive Growth Agent

Plan for our CISTAC 1.0 entry. Read this file and [AGENTS.md](../../AGENTS.md) first, then whichever plan file you're working on.

**Najma** (نجمة, "star") is an AI agent that measures how you think, explains what it sees, and coaches you to improve. You can summon it by voice ("Hey Najma"), talk to it in the web app, or use it from a terminal. It gives you short games, builds a profile of you that changes over time (the Brain Twin), and is always honest about how sure it is.

## Deadlines

Phase 1: **Sun 1 Nov 2026** (public GitHub repo). Final: **Sat 7 Nov 2026**. The build order is in `16`.

## Decisions already made

| Topic | Decision |
|---|---|
| Agent name | Najma ("star"), which matches the night-sky Brain Twin and is a good 3-syllable wake word |
| Personalities | User picks one: Zitouna (calm mentor), Barq (energetic trainer), Hikma (factual analyst), Sahbi (casual friend) |
| Agent framework | LangGraph 1.2.x, with a custom engineered loop (see `03`) |
| LLM | Bring your own key: the user picks Anthropic, OpenAI, Google Gemini, DeepSeek, xAI Grok, Mistral, Groq or OpenRouter and pastes their key, or uses the local Ollama model. Fixed templates if neither works (see `03`) |
| Storage and memory | **Postgres** for all structured data (event log, profile, history, decisions, checkpoints) + **Qdrant** for searchable memory + Markdown notes (`core.md`, journal). No JSON files, no SQLite |
| Games | Classic tests recreated from PEBL and PsyToolkit (ideas only, never their code) on jsPsych 8.3 with our own UI, plus original games |
| Skills measured | 16 dimensions, each tagged Established, Moderate or Experimental |
| Scoring | Kalman-Elo per skill: a score plus an uncertainty that shrinks with play and grows with time away |
| ML models | Growth forecast with honest ranges (Lumosity open data) + engagement risk (OULAD) |
| AI Collaboration Score | Weights V30 / A20 / I20 / C15 / R15, justified in `11` |
| Camera and voice tone | Optional, off by default, local only, weak signal, never touches the profile |
| Interfaces | Web app (main), voice, CLI (last) |
| Dashboard | Based on the team's reference image at `design/reference.png` (style direction still open, see `17`) |

## Files

| File | What's in it |
|---|---|
| [AGENTS.md](../../AGENTS.md) | Rules for the coding agents that build this |
| [01-product-vision.md](01-product-vision.md) | What we're building, for whom, and why it's different |
| [02-architecture.md](02-architecture.md) | System map, tech stack, repo layout |
| [03-agent-langgraph.md](03-agent-langgraph.md) | The agent loop in LangGraph: state, nodes, subgraphs, pauses, checkpoints |
| [04-memory-postgres-qdrant.md](04-memory-postgres-qdrant.md) | How Najma stores and remembers: Postgres tables, Qdrant collections, Markdown notes |
| [05-cognitive-dimensions.md](05-cognitive-dimensions.md) | The 16 skills, how each is measured, known weaknesses |
| [06-games-catalog.md](06-games-catalog.md) | Every game, where it comes from, what it measures, build phase |
| [07-scoring-adaptation.md](07-scoring-adaptation.md) | Score math, uncertainty, difficulty targeting |
| [08-content-generation.md](08-content-generation.md) | How the LLM makes game content safely; custom games |
| [09-coach-explainability.md](09-coach-explainability.md) | Coach, "why" cards, guardrails, Talk to your Twin, experiments |
| [10-ml-models.md](10-ml-models.md) | Trained models, datasets, evaluation |
| [11-ai-collaboration-score.md](11-ai-collaboration-score.md) | The ACS formula and how each part is measured |
| [12-voice-emotion.md](12-voice-emotion.md) | Voice stack, frustration detection, optional camera |
| [13-dashboard-ux.md](13-dashboard-ux.md) | Screens, charts, the night sky |
| [14-ethics-data.md](14-ethics-data.md) | Consent, retention, deletion, Tunisian law |
| [15-evaluation-simulator.md](15-evaluation-simulator.md) | Simulated users, evaluation experiments, robustness checks |
| [16-build-plan.md](16-build-plan.md) | Build order for coding agents: work packages, dependencies, acceptance tests |
| [17-risks-open-questions.md](17-risks-open-questions.md) | What could go wrong and what's still undecided |
| [18-user-workflows.md](18-user-workflows.md) | 22 user workflows, each with its end-to-end test |

## Our honesty rule

We never claim Najma makes you smarter. We claim it measures your practice honestly, explains what it sees, and coaches you at the right level. The research (`17`) shows that's what the evidence supports, and most competitors overclaim.
