# 0019 – General questions about a red-flag topic are answered, not treated as an emergency

Status: accepted (Phase 7)

## Context
A message with a red-flag word gets one of two treatments: the emergency reply (someone may be in
danger now) or, for a general question, the answer with the safety notice in front. The decision was
"starts with a known question word **and** contains no person word". The person list includes "I",
"ich", "my" and "mein-", so "How can I recognise a stroke?" and "Wie erkenne ich einen
Schlaganfall?" were read as "something is happening to me" and got the emergency reply. The RAG evals
bypass this screen, so a golden question (q35) had been wrong all along without anyone seeing it.

Measured first (phrases, then rules): of 28 realistic general questions, **27 got the emergency
reply**. The others failed for a second reason: the question-word list lacked "woran", "wodurch",
"wer" and others, and a greeting in front ("Hello! ...", "Hallo, ...") defeated the start-of-message
check.

## Decision
Keep over-warning when in doubt; flip only the clearly general questions. A question is general if it
has no person in it (as before), **or** it is a *knowledge* question and nothing says it is
happening:
- **A knowledge question** asks to recognise, identify, prevent, avoid, lower, understand, tell
  apart, protect from or find information about something ("how can I recognise ...", "wie erkenne ich
  ...", "woran erkennt man ...", "where can I find information ..."). The verbs are deliberate:
  "how do I **know** if it is a heart attack", "when should I **worry**", "what do I **do**", "should I
  **call**" are questions a person with symptoms asks, and keep the emergency reply.
- **Nothing says it is happening**: no "right now / tonight / gerade / jetzt", no second sentence or
  comma-joined clause, and **no new subject after the question** (a pronoun, or "my/his/her X"
  followed by anything that is not a preposition). The last rule is structural on purpose. A first
  version used a list of verbs ("my husband is/has ...") and a quick test showed that 6 of 7
  unpunctuated narratives slipped through ("how can I recognise a stroke my husband slurs his
  words"): a list never contains the verb nobody listed. Prepositions (`my risk **of**`, `my children
  **from**`, `my mother` at the end) are allowed, so the general questions still pass.
- **Greetings are stripped** before the check, and the question-word lists grew by the words
  that start information-seeking questions (who, whose, whom, should, could, would, will, did; wer,
  woran, wodurch, wofür, weshalb, wieso). A new word was added only if a message without a person word
  starting with it is still a general question.
- The removed marker lists (he/she is/has, ich ... habe) were redundant with the structural rule
  (a mutation check showed they changed no result), so only the temporal markers remain.

## What was checked
Before and after, by treatment (emergency reply / harmful reply / answer + notice / nothing):
- 28 general questions: **27 emergency replies -> 0**; all 28 are answered with the notice.
- 42 genuine emergencies (first or third person, present tense, question-shaped or not, 7 of them
  unpunctuated narratives with unlisted verbs) and 10 ambiguous questions: **all keep the emergency
  reply**; none was lost in any set.
- Red-team (50), routing (100, 12 marked emergency/harmful), RAG golden (65), tuning (34), booking (33
  turns), every German and vocabulary phrase set: unchanged, except the RAG golden question q35 and the
  two pinned false alarms of ADR 0018, which now get the notice.
- The harmful-intent rules are not touched: a lethal-dose question stays a harmful-intent reply
  whatever its form.
- Whole turns: "How can I recognise a stroke?" gets the answer with the English notice,
  "Wie erkenne ich einen Schlaganfall?" the answer with the German notice; the genuine ones never reach
  the model.
- Mutation check, 14 deliberate bugs, each caught (every guard, every list, the greeting strip, the
  structural second-clause rule and each of its three parts).

## Known limits
- The knowledge-verb list is a list: a general question phrased with a verb not on it (for example "how
  can I be aware of ...") keeps the emergency reply. That is the safe direction.
- A knowledge question with a second clause after a comma ("how can I recognise a stroke, a heart
  attack and anaphylaxis?") keeps the emergency reply for the same reason. A list of conditions without
  pronouns ("signs of a stroke, a heart attack, or a seizure") never had one.
- German "sie" counts as a new subject, so a question that ends in the formal "Sie" keeps the emergency
  reply. Again the safe direction.
- Other languages are unchanged.
