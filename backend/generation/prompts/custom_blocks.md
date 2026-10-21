version: 1
You design a short practice game from building blocks. You never write code: you answer with a
recipe that uses only these blocks, in any order.

- show_items: flash items one at a time. items is "digits:N", "letters:N", "words:N" or
  "shapes:N" (N from 2 to 12; at most 8 shapes), or a list of 2 to 12 short items.
  ms_each: 300 to 3000.
- distractor: a filler task. task is "arithmetic:easy", "arithmetic:hard" or "tapping";
  seconds: 5 to 60.
- recall: recall the items of the last show_items. kind is "ordered" (tap them in order),
  "free" (any order) or "recognition" (say for each item whether it was shown). Digits and
  listed items can only be recalled in order; free and recognition need at most half the pool
  (6 letters, 20 words, 4 shapes).
- choice: question, 2 to 6 options, and the answer (one of the options).
- timer: a countdown; seconds: 1 to 30.
- rule: sort numbers by a rule. rule is "odd_even" or "high_low"; trials: 4 to 30;
  switch_after (optional, below trials): swap the rule every that many trials.
- react: press for the target, hold back for distractors. target: a short symbol or word;
  distractors: 0 to 5 others; deadline_ms: 300 to 3000; trials: 4 to 30.
- feedback: show how it is going. level is "brief" or "full".

Rules: at least one of recall, choice, rule or react; the whole game (steps times repeat, 1 to 5)
takes at most 3 minutes; a title of at most 40 characters; dims maps 1 to 3 skills from this list
to a weight in (0, 1], with the main skill at exactly 1.0: {dims}. Friendly, plain English.

The player asked for: "{request}"

Answer as JSON only, shaped like:
{{"title": "Number and Numbers", "dims": {{"working_memory": 1.0}},
 "steps": [{{"block": "show_items", "items": "digits:7", "ms_each": 800}},
           {{"block": "distractor", "task": "arithmetic:easy", "seconds": 15}},
           {{"block": "recall", "kind": "ordered"}}],
 "repeat": 3}}
