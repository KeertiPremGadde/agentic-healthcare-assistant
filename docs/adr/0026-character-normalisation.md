# 0026 – Character normalisation in front of the safety rules

Status: accepted (Phase 7)

## Context
The deterministic rules match plain spellings. The red-team baseline (ADR 0020) and free probes
showed that a message the rules catch in plain text gets through when it is spelled differently:
a zero-width space inside a word, letters separated by spaces or dots, digits for letters ("k1ll"),
look-alike Cyrillic or Greek letters, full-width letters, combining marks, and the typographic
apostrophe in "don't" (which every pattern with `n't` missed). Only the router, a model, was left, and
for some such input (ob03) it returned nothing at all.

Measured first, on 83 obfuscated variants of 12 phrases that the rules catch in plain text (7 techniques,
English and German; harmful, emergency, self-injury) and 4 curly-apostrophe phrases, all written before the
normaliser and in my own transforms, not taken from the red-team cases: **4 of 83 caught (5%), 0 of 4
curly phrases.**

## Decision
`guardrails/normalise.py`: `variants(text)` returns the message itself FIRST, then its folded
spellings. `screen_message` and the guardrail node's safety notice run the rules on each variant and the
first hit wins. Folding can therefore only ADD a safety reply: a message the rules decide about in plain
text keeps that decision exactly, and the user's own text is never changed for the model.

The folds, each with the false alarm it is built to avoid:
- **NFKC, then remove format characters and combining marks that did not compose:** full-width letters,
  ligatures and mathematical letters become plain; zero-width and bidi marks and strike-throughs go; an
  umlaut stays.
- **Typographic quotes and apostrophes become the plain ones.**
- **Cyrillic and Greek letters that look like Latin ones become those letters** (look-alikes only, not
  transliteration).
- **Spaced or dotted letters:** a run of three or more single letters with the SAME separator is joined
  ("k.i.l.l", "h o w   m a n y"); a gap of two or more spaces ends a run. Only inside a message that
  already has such a run are two-letter words joined too ("i.s", "t o"), so "e.g." and "a b" in an ordinary
  sentence are left alone.
- **Digits and `@` `$` inside a word of three or more letters become letters** ("k1ll", "d0se", "l3thal",
  "1ethal"), except in a number glued to a unit ("5mg", "3D", "4weeks"), identifiers ("B12", "COVID19") and
  words with too few letters. "1" is tried as "i" and as "l".
- At most 8 variants per message.

## Results
- The 83 obfuscated variants: **83 of 83** get the reply of the plain phrase (before 4), per technique 12/12,
  12/12, 12/12, 11/11, 12/12, 12/12, 12/12 (zero-width, spaced, dotted, leet, homoglyph, full-width,
  combining). The 4 curly phrases: 4 of 4 (before 0).
- Benign look-alikes (digits, units, ids, abbreviations, spaced initials, other scripts, curly quotes): 0 of 23
  flagged, and 0 of 28 in a second set written after the normaliser. A first version of the measurement-unit
  exclusion also protected "1ethal"; a test with a digit for an `l` caught it.
- All 966 known messages (every phrase list of the safety series, the 195 red-team cases, the 100 routing
  messages), screened plain and folded: 92 change, every one from no reply to a safety reply (83 in the new sets,
  9 red-team cases), none the other way and **none among the other 800-plus messages**. The red-team cases
  newly caught by the rules: ob01-ob08 and ob12, including the three dev cases ob03, ob06 and ob12. They
  were looked at only after the normaliser was finished, so they are a check and not a tuning set; the
  split's single measurement stays at the end of the series.
- 11 mutations (each fold, the second reading of "1", both short-word joins, the measurement exclusion, and "the
  message itself first") each fail a test.

## Not covered (stated)
- **Typos** ("sleping pils", "suiside"): ob09-ob11 stay with the router; fuzzy matching is a different tool.
- **Encodings** (base64, ROT13: ob13, ob14): the router cannot parse them, and the neutral router-failure
  reply (PR #28) answers.
- **A run with single spaces between words** ("k i l l m y s e l f") cannot be told from letter spacing; it
  becomes one word and no rule matches. Pinned in a test; the router is the net there.
- Other leet symbols (`|`, `!`), repeated letters ("kiiill"), and scripts beyond Cyrillic and Greek.
- The rules are English and German only; French and Turkish stay on the list.
