# Demo video script (about 4½ minutes)

The brief asks for 3–5 minutes. Each scene says what to show and what to say. Times are cumulative.

## Before you record

- `make up`, then `make seed`. Open the app and switch on "Demo person" in the sidebar (Alex, four months of data), or open the printed sign-in link.
- Open a **private window** on http://localhost:5173 for the first-visit scene.
- Browser at 1440×900, zoom 100%, bookmarks bar hidden, notifications off.
- Start Ollama (or add a key in Settings → AI provider) so the coach writes fresh replies; check the sidebar doesn't say "Local mode" if you want a hosted model.
- Allow the microphone for localhost if you show voice.
- Do one dry run: the first game after `make seed` is a warm-up game.

## 1. Hook (0:00–0:20)

**Show:** the home page, sky background, "Good evening".

**Say:** "Brain-training apps give you a score and a streak. They don't tell you how sure they are, why they picked a game, or what to do next. Lodestar is an AI agent that measures how you think, keeps an honest profile of you, explains every choice, and coaches you at the right level."

## 2. First visit (0:20–0:45)

**Show:** the private window. Get started → "I'm 18 or older" → the consent screen (one line per switch, Details folded) → pick Willow.

**Say:** "Nothing is stored until you finish this screen. Camera and voice tone are off by default: Lodestar works fully without them, and they can never change your profile. You pick a coach; they all say the same facts in their own voice."

## 3. A session (0:45–1:40)

**Show:** back in Alex's window. Click **Start a session**. On the pick card, click **Why?** and pause on the options and their score parts. Close it, click **Let's go**, play about 20 seconds of the game, let it finish.

**Say (Why card):** "Every pick is a recorded decision. Here are the skills it weighed: how unsure it is about each, how long since you played, your goals. It picked the one with the highest score, and it says why."

**Say (result):** "After each game: the score, the skill it moved with its likely range, never a bare number, and the coach. Every number the coach says carries a citation: tap it to see the fact behind it. A verifier rejects any reply with a number it can't trace, or a clinical word."

## 4. Brain Twin (1:40–2:10)

**Show:** Brain Twin. Hover a card, drag one, point at a grey tag. In **Ask your Twin**, type "when am I sharpest?" and let the answer appear on the page.

**Say:** "This is the Brain Twin. Each card is a skill: the number is the estimate, the bar is the 80% range, and the softer the shadow, the less sure Lodestar is. Grey tags are skills it hasn't measured yet. You can ask your Twin questions, and it answers from your own data, with citations, and says how sure it is."

## 5. Progress and Insights (2:10–2:45)

**Show:** Progress (goal rings, one curve with its forecast band and the life strips), then Insights.

**Say:** "Goals are about certainty: pin working memory down to ±15 points by a date, with rounds left. Curves show the range and a forecast from a model trained on 36,000 real players; its ranges held 80% of the time on players it never saw. Insights put the models in plain words: your best time of day, the minute you start to tire, and whether your confidence matches how often you're right."

## 6. Experiments and the agent (2:45–3:15)

**Show:** Experiments (the "Evening wins" card), then Agent (the five stages, one decision card with its bars).

**Say:** "You can test ideas about yourself: Lodestar ran morning and evening sessions with the same games and gives a verdict only when it's at least 80% sure. And nothing is a black box: the Agent page shows every step of the loop and every decision with the options it weighed."

## 7. AI collaboration (3:15–3:35)

**Show:** AI collaboration page (score, range, five parts). Optionally a few seconds of Spot the AI's Mistake from Games.

**Say:** "The AI Collaboration Score measures how well you work with AI, from what you do: catching planted mistakes in the AI's answers, trying before asking for a hint, retrying after a failure, asking when something's unclear, and taking breaks. It's a documented formula, with a range."

## 8. Voice, memory, privacy (3:35–4:05)

**Show:** press the microphone and say "I slept badly, something easy please". Then Memory: forget one line. Then Settings → Memory & data → Export.

**Say:** "You can just talk to it, and it talks back in your coach's voice. It remembers what matters, and you can see and forget any line. You can export everything or delete everything and get a receipt. It runs with your own AI key, a local model, or none at all."

## 9. Under the hood and close (4:05–4:35)

**Show:** Under the hood: scroll past the architecture, the models and the simulator table.

**Say:** "Under the hood: a LangGraph agent with 22 steps, a Bayesian scoring engine, four models and three stores. We tested it on 200 simulated people with known skills: after three sessions it recovers their true skill with a correlation of 0.82, its 80% ranges contain the truth 80% of the time, and every session still completes when the models or the memory go down. Lodestar: an honest coach for how you think."
