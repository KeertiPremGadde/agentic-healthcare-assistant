# 0016 – German emergency and harmful-intent replies, chosen by the rule that matched

Status: accepted (Phase 7)

## Context
ADR 0015 localised the fixed texts of the medical-answer path. The two most important fixed texts
were still English for a German user: the emergency reply and the harmful-intent (crisis) reply.
They cannot take their language from the router, because the deterministic rules run before any
model call by design (an emergency answer must not depend on an API being up).

## Decision
- **Each rule pattern carries its language.** German patterns are marked with a `str` subclass
  (`_de(...)`) in `emergency.py` and `harmful.py`; nothing else about the rules changed. 28
  emergency patterns and 10 harmful-intent patterns are German. Detection is unchanged: the old and
  the new rules, run side by side on all 247 messages in the repo (red-team set, routing set, RAG
  golden set, tuning set), return the same category and kind for every one.
- **The reply is German only if every pattern that matched is German.** All patterns are checked;
  a mixed message (a German sentence with an English match such as "stroke") gets the English
  reply, the existing default, which also carries 112. The language is on `RedFlag`,
  `HarmfulFlag` and `Screen`, so the guardrail node and the API's daily-limit path (which calls
  `screen_message` directly) get the right reply without further code.
- **When only the router's flags caught a message** (the second layer), its `language` decides, as
  for every other fixed text. The router does not know the category, so a router-flagged emergency
  gets the general emergency reply without the poison line.
- **The safety notice** in front of an answer to a general emergency question follows the turn's
  `reply_language` (set by the supervisor, ADR 0015).
- **Texts** live in `guardrails/texts.py` with the others (`emergency_message`,
  `emergency_poisoning_message`, `harmful_message`, `safety_notice`); the English strings moved there
  unchanged and are re-exported (a test pins their SHA-256 to the values on `main`).

## The German wording (formal "Sie", approved by the maintainer)
- 112, the TelefonSeelsorge (0800 111 0 111, free, anonymous, "rund um die Uhr", verified on
  telefonseelsorge.de; 116 123 also in the harmful reply) and **116 117 (ärztlicher
  Bereitschaftsdienst) only in the emergency reply's "not acute" line**: it is not a crisis line, so
  it is not in the harmful reply.
- **No US numbers (911, 988) in the German texts**; a German-language user is assumed to be in
  Germany or the EU.
- **The poison line** ("Bei schweren Symptomen wie Bewusstlosigkeit, Atemnot oder Krampfanfällen
  wählen Sie sofort die 112." followed by the poison centres) appears **only in the emergency reply
  for the poisoning/overdose category and in the harmful reply** (accidental swallowing). English is
  unchanged.
- **Poison centre numbers** are the seven "Notruf" lines of the BfR directory (Stand 22.07.2026,
  read from the page and from the official PDF): Berlin 030 19240, Bonn 0228 19240, Erfurt 0361
  730730, Freiburg 0761 19240, Göttingen 0551 19240, Mainz 06131 19240, München 089 19240. A
  third-party list still gives an old Göttingen number (0551 383180), which is why the BfR directory
  is the source and a test pins the seven numbers independently. **The directory states no opening
  hours, so none are claimed** for the poison centres (only the TelefonSeelsorge, whose own page says
  "Tag und Nacht erreichbar"). Re-check the numbers when the directory is updated.

## Frontend
The emergency and crisis cards are chosen by message kind, not by text, so German replies get them.
`linkifyPhones` now also makes 116 117, 116 123 and the seven poison lines tappable (it is a fixed
list, not a general regex, so dates and ids never become links); tests include look-alike numbers.
The card chrome (titles, "Call 112") is UI text and stays English, like the "Sources" heading.
The crisis card keeps its plain-text layout: its call buttons carry the numbers, and its collapsible
poison list shows Berlin and München only and links the BfR directory for the rest.

## Known gaps
- A pre-existing detection gap, not changed here because this PR promises unchanged detection:
  "einen allergischen Schock" (accusative) is not matched by the pattern `allergischer schock`.
  A recall improvement for a separate change.
- Other languages (Turkish, French, ...) get the English replies.
- Only the replies are localised, not the rules' coverage: German phrasings the rules miss are
  still caught only by the router's flags.

## Consequences
- German emergency, crisis and poisoning replies are German end to end, with no model call.
- 30 new unit tests, mutation-checked (seven deliberate bugs, each caught): language ignored; a
  mixed message counted as German (emergency and harmful rules); poison line on every German
  emergency or on none; router flags ignoring the router's language; safety notice always English;
  a wrong poison-centre number.
