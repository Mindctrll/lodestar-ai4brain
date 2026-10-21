# 18 · User workflows

Each workflow shows what the user does, what Najma does, what happens underneath, and the end-to-end test that proves it works. Every workflow here becomes a Playwright (web) or pytest (agent) e2e test with the same name.

Example user: **Amira**, 21, engineering student in Sfax, exams in two weeks.

---

## UW1 · First visit and onboarding

**Trigger:** Amira opens the app for the first time.

1. Welcome screen: one sentence on what Najma is, and that it's a practice coach, not a medical tool.
2. Age check (18+).
3. Consent in plain words, with separate switches: core practice data (required), cloud AI, microphone, camera (off), deliberate-mistake games (explained). She turns the microphone on and leaves the camera off.
4. Pick a coach: Zitouna, Barq, Hikma or Sahbi, each with a one-line sample and a voice preview. She picks Zitouna.
5. Najma: "Let's do a 5-minute warm-up so I can get to know you. Nothing here is a test you can fail."
6. Quick Draw first (also measures device lag), then 5 short games from different skills, each 40–60 seconds, at Assess difficulty (60–70% success).
7. Result: the night sky appears with every constellation blurry. Najma explains: "I've got a first rough picture. The blur means I'm not sure yet. It sharpens as we play."
8. Najma suggests a goal or lets her skip.

**Underneath:** `app.users` and `app.consent` rows; `session.started`; graph runs in Assess mode for the onboarding battery; one scored-round transaction per game; `core.md` created with persona and first facts; Qdrant gets one `episodic` point ("first session").

**Test `uw1_onboarding`:** new user completes consent and 6 games → 6 rounds in `twin.rounds`, σ below 0.8 on the core skills (those the battery measures with a primary loading, `07`), persona saved, camera never initialised.

---

## UW2 · Daily session, Najma decides

**Trigger:** Amira taps the orb on the Home screen.

1. Home already shows today's suggestion with its reason: "Memory today. It's the skill I'm least sure about and you last practised it 9 days ago."
2. She taps **Start**. Souk Rush runs at Balanced difficulty (about 80% success).
3. After-game screen: "Nice. You filled 9 of 11 orders [F3]. Your memory estimate rose a little [F2], and I'm more sure about it now [F1]." Each tag is a tappable why chip.
4. Najma picks the next game (a different skill), or ends after 3 rounds or when fatigue rises.
5. Session end: short summary, Twin updated live, next suggestion shown.

**Underneath:** `perceive` fan-out → `plan_next` writes a `Decision` → exercise subgraph pulls validated content from the pool → `play` pauses → browser resumes with results → `score_update` transaction → `monitor` → `reflect` → coach subgraph (verified) → `remember` → loop or `consolidate`.

**Test `uw2_daily_session`:** 3 rounds complete; each has a decision with a reason; every coach number maps to a fact id; dashboard receives `twin_updated`.

---

## UW3 · Amira declines the suggestion

1. Najma suggests memory. Amira: "Not memory today, something quick."
2. Najma: "Sure. Here's a 1-minute speed game instead." It remembers the preference for today only.
3. If she declines the same skill three sessions in a row, Najma says once: "You've skipped memory for a while. Want a short round, or should I stop suggesting it this week?"

**Underneath:** `route_intent` → policy raises the weight of quick games for this session; `Decision` records the user override; a `memory.written` point if the pattern repeats.

**Test `uw3_decline`:** declined skill isn't chosen again in that session; after 3 declines the nudge appears once, not every time.

---

## UW4 · Voice summon with a specific request

**Trigger:** Amira says "Hey Najma, give me a memory game about football."

1. The orb lights up, and a caption shows the transcript.
2. Najma (spoken and on screen): "Football memory, coming up." It loads Market List with football words at her level.
3. She plays; Najma reads the result aloud.

**Underneath:** wake word (or tap-to-talk) → STT → `ingest` → `route_intent` = play with game and theme → exercise subgraph generates content with theme "football" → validators (including novelty) → `play`.

**Test `uw4_voice_request`:** recorded audio fixture "give me a memory game about football" → a word-recall exercise starts with a football theme and correct difficulty.

---

## UW5 · Frustration mid-session

1. In Arrow Storm, Amira misses 4 in a row and slows down.
2. Inside the game, the frame offers: "Want it a bit easier?" She taps yes, and the game finishes at a lower level.
3. After the game, Najma (Zitouna tone): "That one was tough. Let's do something lighter, or take a 2-minute break?"
4. A small "Was I right?" button lets her confirm or reject the frustration guess.

**Underneath:** browser behaviour signals → `frustration_p` → game resumes the graph with `status: stopped` or `eased` → `monitor` routes to ease or break → feedback stored as a label. **No change to the profile from affect.**

**Test `uw5_frustration`:** scripted miss streak triggers the in-game offer and an easier next pick; a test confirms no profile row changed because of affect.

---

## UW6 · Refresh or crash mid-game

1. Amira's laptop closes during Echo.
2. She reopens the app later. Home shows: "You were in the middle of Echo. Resume or skip?"
3. Resume restarts that game; skip moves on. Nothing is scored twice.

**Underneath:** the graph is paused at `play` in the Postgres checkpointer; the app reloads the thread state; resume uses the same `round_id`, so idempotency holds.

**Test `uw6_resume`:** kill the browser and server during `play` → restart → resume completes the round once.

---

## UW7 · "Why did you pick that?"

1. Amira types or says: "Why memory again?"
2. Najma: "Because it's still the skill I'm least sure about (range ±14) [D7], and your exam plan puts memory first this week [F5]." Tapping D7 shows the decision card: the top 3 candidates with their score breakdown.

**Underneath:** converse subgraph → tool `explain(decision_id)` → reads `agent.decisions` → facts packet → verified reply.

**Test `uw7_explain`:** the answer cites the latest decision id and its numbers match `agent.decisions`.

---

## UW8 · Talk to your Twin

1. In the Twin screen Amira asks: "When am I sharpest?"
2. The Twin answers in first person: "My focus games go best in the evening, 84% after 20:00 vs 76% before noon [F11]. That's only 9 sessions, so I'm not sure yet [F12]. Want to test it this week?"

**Underneath:** twin chat subgraph → time-of-day aggregates from `twin.trials` → facts packet → verified reply → optional hand-off to UW10.

**Test `uw8_twin_chat`:** seeded data with a known time-of-day difference → the answer states the right direction, cites facts, and mentions uncertainty.

---

## UW9 · Life context: "I slept badly"

1. Amira, before a session: "I slept like 4 hours."
2. Najma: "Thanks for telling me. I'll keep today light, and today's results will count less toward your profile."
3. The progress curve later shows a shaded strip for that day labelled "slept badly".

**Underneath:** converse tool `log_life_context` (confirms first) → `twin.life_context` row with a period and weight 0.5 → scorer applies `context_weight` → `core.md` not changed for a one-off.

**Test `uw9_life_context`:** rounds inside the window count as half the evidence (weight 0.5). In the Kalman update the mean moves about 60% as far as for identical rounds outside the window, and the range shrinks less.

---

## UW10 · Personal experiment

1. Najma (from UW8, or on its own): "Want to test whether you focus better in the evening? 6 sessions over 6 days, alternating morning and evening, same 3 games."
2. Amira agrees. The plan screen shows the experiment with progress dots.
3. Each day, Home suggests the session for that day's condition.
4. After 6 sessions: a result card. "Evening was better in 5 of 6 comparisons. Probability evening is better: 0.83. I'll suggest evening sessions from now on."
5. If inconclusive, it says so plainly.

**Underneath:** experiment subgraph → consent `interrupt` → `agent.experiments` row → `plan_next` priority → Bayesian comparison → result card + `facts` point in Qdrant.

**Test `uw10_experiment`:** simulated user with a hidden evening advantage → experiment completes with probability > 0.7 in the right direction.

---

## UW11 · Set and track a goal

1. Amira: "I want my memory to be solid before exams."
2. Najma turns it into a measurable goal: "Let's aim for your memory range to be within ±5 by 3 Nov. That means about 6 more memory rounds."
3. The goal card on Progress shows the range shrinking toward the target.

**Underneath:** `set_goal` tool (confirm) → `app.goals` → `goal_weight` in the policy → goal chart.

**Test `uw11_goal`:** after setting the goal, memory is chosen more often, and the goal progress endpoint reflects σ.

---

## UW12 · Spot the AI's Mistake (and the Collaboration Score)

1. Najma solves a pattern puzzle step by step: "Step 3: the shape rotates 90° each time, so the answer is B."
2. Amira must flag the wrong step or confirm the solution is right. She spots the error in step 3.
3. Najma: "Good catch. I had it rotating the wrong way." The ACS screen updates its verification component.

**Underneath:** content pipeline plants an error (70% of items) and the solver confirms it → `acs.observed` events → ACS Beta posteriors.

**Test `uw12_spot_mistake`:** planted-error items are always really wrong; correct items always really correct; ACS V updates on both kinds.

---

## UW13 · Ask for a diagnosis

1. Amira: "Do I have ADHD? My focus scores are low."
2. Najma: "I can't tell you that. I only measure practice in these games, not health. If you're worried about your focus, a doctor or psychologist is the right person to ask. Want to keep practising, or look at what helps focus in these games?"

**Underneath:** `safety_gate` → fixed refusal template → no LLM free text for this reply.

**Test `uw13_diagnosis_refusal`:** 30 phrasings of diagnosis requests all get the template; no condition names appear in Najma's reply.

---

## UW14 · See, edit, export, delete my data

1. Settings → **Memory & data**: Amira sees `core.md` lines, life context entries, and memories Najma kept.
2. She deletes "Usually plays in the evening". It's gone from `core.md` and from Qdrant.
3. **Export** gives her a download of everything.
4. **Delete everything** asks for confirmation inside the page, then shows a receipt: "Deleted 1,284 events, 46 rounds, 23 memories, 12 sessions."

**Underneath:** memory edit → Markdown update + Qdrant delete by point id; export built on request; delete job → Postgres cascade + `adelete_thread` per session + Qdrant filter delete + notes folder removed + `app.deletion_receipts` row.

**Test `uw14_data_rights`:** after delete, zero rows, points, checkpoints and notes remain for that user; the receipt counts match what existed.

---

## UW15 · Coming back after a long break

1. Amira returns after 3 weeks.
2. The night sky is blurrier. Najma: "Welcome back. It's been 3 weeks, so I'm less sure about you than before. A quick 4-minute check-up?"
3. A short Assess-mode battery on the skills that drifted most, then normal training.

**Underneath:** staleness drift widens σ → policy switches to Assess mode for high-σ skills → engagement-risk model (wave 3) keeps the first session short.

**Test `uw15_long_gap`:** after a 21-day gap, σ has grown per the drift rule and the first session is in Assess mode.

---

## UW16 · Camera on (optional)

1. Settings → camera switch → separate consent screen explaining: local only, never stored, only used to suggest breaks, never affects scores.
2. A small "Camera signal in use" indicator appears during games.
3. When strain cues and behaviour both rise, Najma suggests a break. If only the camera signal rises, nothing happens.

**Underneath:** MediaPipe in the browser → `strain_cue` every 10 s → fused with behaviour (weight ≤ 0.3) → affects tone and breaks only.

**Test `uw16_camera`:** no network request carries image data; camera-only rise doesn't trigger a break; profile unaffected.

---

## UW17 · Ask for a brand-new game

1. Amira: "Make me a game where I remember a phone number while doing maths."
2. Najma: "Building it." The game runs from blocks (show digits, maths distractor, ordered recall).
3. After: "Fun one. Since it's new, I'm only counting it a little toward your profile."

**Underneath:** LLM writes a recipe → validator → block engine → scoring with reliability 0.3–0.5.

**Test `uw17_custom_game`:** the request yields a valid recipe that runs; the profile update is smaller than for the equivalent classic game.

---

## UW18 · Private mode / AI offline

1. Amira turns off cloud AI in settings (or her provider goes down, or her key runs out of credit).
2. Najma keeps working with the local model; a small badge says "Local mode". If the local model is unavailable too, games and scoring still work and the coach uses short fact-based templates.

**Underneath:** LLM interface switches backend → degradation recorded in state and trace.

**Test `uw18_offline`:** with the hosted LLM blocked, a full session completes; with all LLMs blocked, a full session completes with template coaching.

---

## UW19 · Terminal (CLI)

```
$ najma chat
Najma (Hikma): Good evening. Memory is your least certain skill (±12). Play a round? [y/n]
> show my profile
Working memory   64%  (52–75)   ▓▓▓▓▓▓░░░░
Inhibition       71%  (63–78)   ▓▓▓▓▓▓▓░░░
...
> set goal memory ±5 by 3 Nov
Najma: Goal set. About 6 memory rounds needed.
```

Text-friendly games (Digits Back, Quick Maths, Logic Lock) can be played in the terminal; others open in the browser.

**Underneath:** CLI → MCP tool server → same agent and tools as the web app.

**Test `uw19_cli`:** chat, profile view and goal setting work through the CLI and match the web app's data.

---

## UW20 · Change coach or difficulty mode

1. Settings → coach: Amira switches from Zitouna to Barq. The next message is shorter and punchier; the facts are identical.
2. Difficulty mode: Chill / Balanced / Push. She picks Push; games now aim for about 65% success, and Najma says so.

**Underneath:** `app.users.persona`, `success_mode` → persona style block and p* target.

**Test `uw20_persona_mode`:** same facts packet rendered by two personas passes the same verifier; Push mode shifts achieved success to 65 ± 5% on the simulator.

---

## UW21 · Voice tone on, and a spoken game

1. Settings → **Voice tone** switch (separate from the microphone switch). Consent screen: Najma will look at how fast she speaks, pauses and pitch changes, compared only with her own usual voice; audio is never kept; it only affects tone and break suggestions.
2. Her first 10 voice requests build her baseline quietly. A "Voice signal in use" indicator shows while she speaks.
3. Late at night she says, slowly, with long pauses: "Hey Najma… um… one more game." Her recent games also show slowing. Najma: "You sound a bit tired, and your last round was slower than usual. One short game, then rest?"
4. She plays Word Burst in spoken mode: says as many words starting with "B" as she can in 60 seconds. The transcript is scored; the audio is discarded.

**Underneath:** STT for the request; `AudioWorklet` features → z-scores vs her baseline → `voice_strain_cue` → fused with behaviour (≤ 0.3) in `read_affect` → `monitor` suggests a break. Spoken game answers are scored from the transcript only.

**Test `uw21_voice_tone`:** recorded slow, hesitant fixture plus a behaviour slowdown triggers the break suggestion; the voice cue alone does not; no audio leaves the browser; profile unaffected.

---

## UW22 · Bring your own AI key

1. Settings → **AI provider**. Amira sees the eight providers and "Local (no key)".
2. She picks Gemini and pastes her key. Najma makes one small test call: "Key works. Using Gemini." The key now shows as `••••a91F`. If the key is wrong: "That key didn't work. Check it and try again." Nothing is saved.
3. Before cloud AI turns on, the consent screen names the provider and where it processes data.
4. Later she switches to Groq. Coach replies come from the new model; the facts are identical.
5. She removes the key. Najma moves to local mode and shows the "Local mode" badge.

**Underneath:** `PUT /llm/credentials/gemini` → test call → AES-GCM encrypt → `app.llm_credentials` → `PUT /llm/selection` → `llm.selection_changed` event (no key) → the LLM factory decrypts in memory per call.

**Test `uw22_byok`:** with a canary key and a recorded-response stub for each provider: valid keys are saved and shown as last 4 characters only; invalid keys are rejected and not saved; the canary string never appears in logs, traces, checkpoints, events or the export; the same facts packet passes the verifier with two providers; removing the key falls back to local mode.

---

## Where these go in the build

| Wave gate (`16`) | Workflows that must pass |
|---|---|
| Wave 1 | UW2 (stub coach), UW6 |
| Wave 2 | UW1, UW2, UW3, UW4 (tap-to-talk), UW5, UW7, UW9, UW11, UW12, UW13, UW14, UW15, UW18, UW20, UW22 |
| Wave 3 | UW4 (wake word), UW8, UW10, UW16, UW17, UW19, UW21 |
| Wave 4 | All, in CI |
