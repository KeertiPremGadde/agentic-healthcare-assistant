# 0015 – Fixed medical-answer texts in German, chosen per turn

Status: accepted (Phase 7)

## Context
Since ADR 0014 a German medical question is retrieved with an English query and answered by the
model in German. The sentences the assistant says itself were still English: the "I don't know"
reply, the dose referral, the `Sources:` / `Content:` labels and the disclaimer. The output guard
and the frontend's reply parser both looked for those English strings, so changing only the
backend would have broken the guard (a German reply without "Sources:" is "uncited") and the
display (sources inline, no disclaimer styling).

## Decision
- **`guardrails/texts.py`** holds a `FixedTexts` set per language, English and German. They are
  reviewed wording, not model output: a safety sentence is not something to generate or translate on
  the fly. The module has no imports, and the existing English constants (`DISCLAIMER`, `NO_ANSWER`,
  `DOSE_REFERRAL`) are re-exported from it, so English output is byte-identical (a test pins the
  literal strings).
- **The language is decided once per turn** from the router's `language` (already returned by the
  call from ADR 0014) and stored as `reply_language` in the state, set by the supervisor on every
  routed turn so it can never be stale. Only German has its own set; any other language (Turkish,
  French, ...) falls back to English rather than guessing a translation.
- **The output guard checks against every language** and adds in the turn's language. A reply is
  "cited" if it has any language's sources label, "fixed" if it starts with any language's refusal or
  dose referral, and complete if it contains any language's disclaimer; all disclaimers are removed
  before the dose check. So a correct German reply is never replaced by an English refusal, and a
  reply is never given a second disclaimer in the other language.
- **The frontend parser mirrors the labels** (`Quellen:`, `Inhalt:`, the German disclaimer start);
  the contract is noted in both `texts.py` and `citations.ts`. The "Sources" heading in the UI is
  UI text and stays English for now.
- **Dose guard, German vocabulary.** German medical answers started flowing with ADR 0014, so the
  guard now also knows Teelöffel, Esslöffel, Zäpfchen, Beutel, Pflaster, Hub/Hübe, Spritze, Ampulle,
  Dragee, Milliliter and "einen". Kept out on purpose: "i.e." as a unit (German "I.E.") because it
  would flag English text like "type 2 i.e. insulin resistant". Accepted false alarms, in line with
  the guard's stated preference: "ein Pflaster", "eine Spritze" in a non-dose sense.

## Not in this change
- The emergency and harmful-intent replies, the safety notice, the doctor note and the smalltalk /
  out-of-scope replies are still English. The emergency and harmful replies are the important ones:
  they run before the router, so the language has to come from the rule that matched. Next PR.
- Other languages beyond German; the UI strings.

## Consequences
- German turns are German end to end except those fixed replies; unit tests cover the guard, the
  rendering, whole turns (answered, refused, unknown language, language changing between turns) and
  the dose forms, and were mutation-checked (four deliberate bugs, each caught). One `llm`-marked test
  checks that the real router reports `de` and an English query for German questions and `en` and
  none for English.
- The answer body is unchanged, so no judged re-run was needed.
