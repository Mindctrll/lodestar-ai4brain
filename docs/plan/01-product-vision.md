# 01 · Product vision

## One sentence

Lodestar is an AI agent that runs your thinking-skills practice: it measures you with short games, keeps an honest, changing profile of you, explains what it sees, and adapts your training, all without ever pretending to diagnose anything.

## Who it's for

Students and young adults who want to understand and improve how they focus, remember and reason, for example while studying for exams. The typical user is a Tunisian university student.

## What the user experiences

1. **First visit.** Plain-language consent with separate switches for camera, microphone and cloud AI. Pick a coach personality. A 5-minute warm-up of about 6 quick games gives a rough first profile with wide uncertainty.
2. **Every session.** Say "Hey Lodestar", tap the orb, or type. Lodestar checks your profile, history, memory of past chats and your current state, then picks what to do and says why: "Your memory reading is still blurry and you haven't practised it in 9 days. One round?"
3. **During games.** Difficulty adapts so you succeed about 75–85% of the time when training. If you start struggling (mistake streaks, slowing down), Lodestar eases off or suggests a break.
4. **After games.** The coach explains what changed, with tappable "why" cards linked to your real data.
5. **Over weeks.** The Brain Twin (a night sky where each skill is a cluster of stars) gets sharper as Lodestar learns about you. Forecasts appear as ranges. You can chat with your Twin, set goals, tell Lodestar about your life ("exam week"), and agree to small personal experiments ("Do you focus better before noon?").

## Lodestar and the four personalities

Lodestar is one agent with one set of rules. The personality only changes how it talks, never what it decides or what facts it states.

| Persona | Meaning | Style | Voice |
|---|---|---|---|
| **Willow** | Willow tree | Calm mentor. Patient, warm, uses metaphors of growth | Slow, low |
| **Spark** | Lightning | Energetic trainer. Short sentences, challenges, celebrates streaks | Fast, bright |
| **Sage** | Wisdom | Factual analyst. Numbers first, minimal emotion, shows the ranges | Neutral |
| **Buddy** | A close friend | Casual friend. Jokes, plain English | Relaxed |

## What makes us different (our innovation story)

Commercial apps (Lumosity, Elevate, Peak, NeuroNation, CogniFit, BrainHQ) give fixed workouts and a single score. Lodestar adds:

1. **A real agent loop** that decides, acts and explains, instead of a fixed workout.
2. **Uncertainty everywhere.** Scores come with ranges that shrink with practice and grow with time away, and the visuals show it.
3. **Coaching that cites its evidence.** Every claim links to the data behind it, and a validator blocks anything it can't back up.
4. **An AI Collaboration Score** measured from behaviour, which no competitor has.
5. **Personal experiments** with consent and confidence reporting.
6. **Life context** that keeps a bad night from counting against you.
7. **Local-first privacy, your choice of AI:** an offline local model, or your own key for one of eight hosted AI providers; camera processing on the device only.
8. **Honest claims.** We say "you'll get better at what you practise", not "you'll get smarter".

## Claims we make and claims we never make

| We say | We never say |
|---|---|
| You improve at what you practise | Boosts IQ, rewires your brain |
| Here's your current pattern and how sure we are | You have a focus problem / deficit |
| Practising at the right difficulty helps learning | Prevents decline, treats anything |
| This is a statistical estimate | This is who you are |

Background: Simons et al. (2016) found strong evidence for gains on trained tasks and little for distant tasks or daily life. The US FTC fined Lumos Labs in 2016 over unsupported advertising claims. Honest claims set us apart.

## Build waves

The full build order is in `16`.

- **Waves 0–2 (core product):** Layers A–C, ACS, ethics, 15 games, the agent loop, memory, dashboard, growth forecast model, tap-to-talk voice, conversation, simulator results.
- **Wave 3 (advanced):** wake word, Talk to your Twin, personal experiments, engagement-risk model, fatigue model, bandit, the remaining games, CLI, camera strain cues, custom games from blocks, detective story mode.
- **Wave 4:** hardening and the evaluation suite.
