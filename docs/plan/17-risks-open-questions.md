# 17 · Risks, evidence and open questions

## Open questions

| Question | Needed by |
|---|---|
| Dashboard style: the reference (`design/reference.png`) is a light task-manager look, the Brain Twin is a dark night sky. Light app with a dark sky card, dark app throughout, or a light sky? | WP2.5 |
| The challenge brief PDF: judging criteria for Phase 1 and the final (the weights in this plan add up to 95%) | Now |
| Operator LLM key for background jobs (optional; Ollama otherwise) | WP2.2 |
| Porcupine access key and current free-tier terms | WP3.4 |
| Licence of each `jspsych-contrib` package we use | Before the package is used (WP2.1, WP3.1) |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Parallel agents build against different interfaces | Integration breaks | Contracts frozen in WP0.2; contract changes go through the integrator first |
| Many games, uneven quality | Buggy or inconsistent games | Shared game frame, per-game Playwright and metric fixture tests, same Definition of Done |
| LLM latency or outage | Stalled sessions | Content pools, template fallbacks, local Ollama |
| LLM invents facts in coaching | Explainability and trust loss | Facts packets + verifier + template fallback |
| A user's API key leaks | Their money and account at risk; trust loss | Encrypted at rest, decrypted only in the LLM factory, never in state or checkpoints, log redaction, canary-key test (`AGENTS.md` rule 9) |
| Providers differ (structured output, tool calling) | Some nodes fail on some providers | Capabilities in the registry; fallback to Ollama, then templates; a contract test per adapter |
| Unreliable individual scores | Weak profile quality | Multi-task scoring, ranges, reliability notes in the dimension docs |
| Camera feature seen as unethical | Safety | Off by default, local, weak, never in the profile, Barrett + AI Act framing |
| Wake word false triggers | Annoying UX | Tap-to-talk fallback always visible; false-trigger test |
| Profile and event log drift apart | Wrong scores | One transaction per round, per-user advisory lock, unique round ids, rebuild-from-events test |
| Slow dashboard queries as events grow | Laggy UI | Indexes on `(user_id, ts)`, monthly partitions, materialised views refreshed after sessions |
| Qdrant local mode lacks a feature | Test vs prod mismatch | Run Qdrant server in Docker for integration tests |
| Requirements change late | Rework | Registry-driven design, simulator, extensibility drill (WP4.4) |
| Copying GPL code by accident | Licence violation in a public repo | `AGENTS.md` rule; review of every reused file; `THIRD_PARTY.md` |

## What the evidence supports (for in-app claims and docs)

- **Training gains:** people get better at what they practise; transfer to distant tasks and daily life is weak (Simons et al. 2016, *Psychological Science in the Public Interest*).
- **The ACTIVE trial** reported some long-term effects of speed-of-processing training in older adults; mention carefully as debated.
- **FTC vs Lumos Labs (2016):** settlement over unsupported advertising claims. Our honest-claims policy follows from this.
- **Reliability paradox:** classic tasks give robust group effects but modest individual reliability (Hedge et al. 2018). Hence ranges and multi-task scoring.
- **Difficulty targets:** 70–85% is an evidence-informed default (staircases, Wilson et al. 2019 for training, Math Garden practice). Wilson's result is theoretical, for simple learners, so we treat it as a default, not a law.
- **Norms** from online English-speaking users may not fit Tunisian students.

## Sources

- Simons et al. (2016): https://journals.sagepub.com/doi/abs/10.1177/1529100616661983
- Hedge, Powell & Sumner (2018): https://orca.cf.ac.uk/102138/1/Hedge.%20The%20reliability%20paradox.pub.pdf
- PEBL battery paper (Mueller & Piper 2014): https://www.academia.edu/19306049/The_Psychology_Experiment_Building_Language_PEBL_and_PEBL_Test_Battery
- PsyToolkit legal terms: https://www.psytoolkit.org/legal.html
- jspsych-timelines: https://github.com/jspsych/jspsych-timelines
- jspsych-contrib: https://github.com/jspsych/jspsych-contrib

Not re-verified in the research: exact licences of Ollama models, DeepFace, HSEmotion, EdNet and ASSISTments; ACTIVE and FTC details.
