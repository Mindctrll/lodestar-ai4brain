# 09 · Coach, explainability and guardrails

## Facts packets: the coach can only say what the data shows

Before the coach speaks, `reflect` (or the Twin chat) builds a **facts packet**: numbered, checked facts from this user's data.

```json
{
  "facts": [
    {"id": "F1", "text": "Working memory estimate 0.66 (80% range 0.55–0.77)", "dim": "working_memory", "events": ["01JB…", "01JB…"]},
    {"id": "F2", "text": "Working memory rose from 0.61 to 0.66 over the last 5 sessions"},
    {"id": "F3", "text": "Accuracy in Echo 3-back: 78% today vs 64% on 14 Oct"},
    {"id": "F4", "text": "Average answer time in Arrow Storm rose 18% while errors fell"},
    {"id": "F5", "text": "Life context: exam week, 3–14 Nov"},
    {"id": "D7", "text": "Chose memory because it was the least certain skill and 9 days unpractised", "decision": true}
  ],
  "knowledge": [
    {"id": "K2", "text": "Grouping items into chunks helps remember longer lists", "source": "registry knowledge base"}
  ],
  "memories": [{"id": "M4", "text": "Said she prefers fewer timed games (22 Oct)"}]
}
```

The coach LLM must tag every claim with ids: "Your memory is climbing [F2], and 3-back went from 64% to 78% [F3]."

## The verifier (runs before anything is shown)

1. Every sentence that contains a claim has at least one valid id.
2. Every number in the text appears in the cited fact (exact or rounded the same way).
3. No forecast is stated as a certainty: forecasts must carry their range.
4. Clinical language filter passes.
5. Persona style rules pass (length, tone).

Failure → repair with the list of violations (max 2) → template fallback built only from facts. We log the **first-draft pass rate** and the **final pass rate (100%)** as a faithfulness metric.

## "Why" cards

In the UI, each `[F#]` or `[D#]` becomes a small tappable chip. Tapping it opens a card showing the fact, a mini chart, and the events behind it. `[D#]` cards show the decision: candidates, score breakdown and the winner. This is our answer to the Explainability criterion (15%).

## Personas (style only)

Each persona is a style block in the prompt plus a TTS voice and rate. **Personas never change facts, decisions or safety rules.** The verifier checks the output in the same way for all of them.

| Persona | Style block (summary) |
|---|---|
| Zitouna | Calm, patient, growth metaphors, max 4 sentences, ends with one gentle suggestion |
| Barq | Short punchy sentences, celebrates streaks, ends with a challenge |
| Hikma | Numbers and ranges first, neutral tone, no exclamation marks |
| Sahbi | Friendly and casual, light humour, the occasional Tunisian word ("yezzi", "behi") with meaning clear from context, English otherwise |

## Language guardrails

**Banned in user-facing text** (lexicon + LLM check, with replacements):

| Never | Use instead |
|---|---|
| deficit, impairment, disorder, dysfunction | growth area, practice area |
| diagnosis, symptoms, treatment, therapy | profile, pattern, practice |
| ADHD, dementia, dyslexia, any condition name | (not mentioned; redirect if the user raises it) |
| IQ, brain age, mental age | skill estimate |
| normal / abnormal | typical range / outside the typical range |
| your brain is… | your results show… |

`make lint-language` checks UI strings, prompts and a red-team list of 200 tricky outputs.

**If the user asks for a diagnosis** ("do I have ADHD?"), `safety_gate` routes to a kind, fixed reply: Najma can't and doesn't assess conditions, its scores are practice estimates only, and a doctor or psychologist is the right person to ask. If the user writes something suggesting crisis or self-harm, Najma stops the training flow and shows support resources.

## Talk to your Twin

The Twin answers in first person, grounded the same way:

> **You:** When am I sharpest?
> **Twin:** My focus games go best in the evening: average accuracy 84% after 20:00 vs 76% before noon [F11], but that's only 9 sessions, so I'm not sure yet [F12]. Want to run an experiment on it?

Twin chat builds its facts packet from the question: time-of-day aggregates, trends, best and worst days, life context.

## Personal experiments

1. **Hypothesis** comes from data ("evening accuracy looks higher") or the user.
2. **Consent:** Najma explains the plan (for example, 6 sessions, alternating morning and evening, same games) and asks; the graph pauses for the answer.
3. **Schedule:** sessions are tagged with the condition; `plan_next` gives them priority.
4. **Analysis:** Bayesian comparison of the two conditions (difference in mean score with a credible interval), reported as "probability evening is better: 0.83".
5. **Result card:** what was tested, how sure we are, what changes in the plan. Inconclusive results are reported as inconclusive.

**As built (WP3.2).**
- **Twin answers** come from `backend/agent/twin.py`: accuracy by morning (5-12), afternoon and evening (18-24) in the user's time zone. A Beta posterior gives the probability the best window really beats the worst, and the Twin calls itself sure only at 0.9 and 15 sessions. It speaks through the same verifier, with a first-person style; the fallback template also states the direction and how sure it is.
- **Offers:** when the Twin isn't sure it offers an experiment, and "yes" next turn starts the proposal. Questions about things Najma doesn't record (coffee, music) get a plain "I don't know that yet".
- **Experiments:** a converse tool with the usual yes/no step. Three sessions in each window, with the three games the person plays most. A session counts by its local start time, and the Experiments page shows progress dots.
- **Analysis:** a difference in mean round score with a pooled variance, normal approximation and 80% credible interval. A winner only at P ≥ 0.8, otherwise "inconclusive". The result card's numbers are facts, and a conclusive result is saved as a memory fact.

## Coaching content beyond numbers

Tips come from the `knowledge` collection (`04`), written by the team with sources, never invented by the LLM. Each tip has an evidence level. Example tips: chunking for lists, slowing down when errors climb, spacing practice, sleep and breaks (general wellbeing, not medical advice).
