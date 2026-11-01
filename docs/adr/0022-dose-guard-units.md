# 0022 – The dose guard sees amounts per kilogram and per day, and grams

Status: accepted (Phase 7)

## Context
The dose guard (ADR 0009) replaces any answer that states a dose of a medicine. The red-team probes
(ADR 0020) showed three holes: "10 mg/kg", "40 mg/day" and "25 mcg/h" slipped through, because the unit
pattern refused anything followed by a slash (to keep lab values such as "100 mg/dL" out), and plain
grams ("4 g per day", "one gram", "4 Gramm") were left to the prompt rule because grams are also food.
Haiku never repeated a dose from an injected passage in 585 runs, so the holes were latent, not exploited;
a different model may behave differently.

Measured first on 29 sentences written before the change, in the way an answer would state a dose or a
look-alike (19 English and 10 German doses; 29 benign: lab values, nutrition, hours, serving sizes):

| | before | after |
|---|---|---|
| doses caught | 4 of 29 | 29 of 29 |
| benign flagged | 0 of 29 | 0 of 29 |

## Decision
Two additions to `guardrails/dose.py`, both structural:

1. **Rates.** A number with a medicine unit followed by `/`, `per`, `pro` or `je` and a denominator
   (kg, day, dose, hour, minute, Tag) counts: "10 mg/kg", "0.5 mg/kg/day", "25 mcg/h", "10 mg pro kg". The
   denominator must end the word, so "mg/dL" (a `d` followed by `L`) and "g/L" stay lab values.
2. **Grams.** "4 g", "4 grams", "4 Gramm", "one gram" count, except "g/dL", "g/L" and "gram-negative".
   Grams are also food, so the check works one sentence at a time: a sentence with a nutrition word
   (fiber, protein, salt, serving, eat, Ballaststoffe, ...) is exempt, unless the same sentence mentions
   taking a medicine (take, give, dose, tablet, paracetamol, nehmen, ...). So "Aim for 30 g of fiber a day"
   passes and "Take 4 g of paracetamol with food" does not. Splitting on sentences also keeps a
   nutrition sentence next to a dose sentence from hiding the dose; decimal points do not split.

The production guard now catches everything the stricter red-team check (`strict_dose`) catches on the
phrase lists, and a test keeps it that way.

## Results
- Phrase sets: 29 of 29 doses (before 4); 0 of 29 benign look-alikes.
- Six mutations (each rule removed in turn) each fail a test. One survived at first because the benign
  sentence never reached the `gram-negative` rule; a test with a number word was added.
- Knowledge base: of 44,158 MedlinePlus sentences, the old guard flagged 23; the new rules add 3, all
  false alarms ("a standard drink contains about 14 grams of pure alcohol", "10 to 25 grams of it per day",
  "2 grams of them per day"). The cost of the safe side, stated: an answer quoting them is replaced by the
  dose referral.
- End to end, the 8 dev dose cases (do01, do04, do07, do10, dc01, dc04, dc07, dc10), 3 repeats, real models:
  24 of 24 passed, $0.0125. The test split is measured once, at the end of the must-fix series.

## Consequences
- The unit list is explicit (mg, mcg, µg, ml, IU, units, Einheiten for rates; g for grams). A new unit
  needs a new entry. The nutrition and medicine word lists are short lists and will miss a food or a
  drug nobody listed: a missed food is a false alarm, a missed drug name only matters inside a nutrition
  sentence.
- Concentrations ("125 mg/5 mL") are still not counted.
