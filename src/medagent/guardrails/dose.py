"""Dose guard: a medical answer must never contain a specific dose or quantity of a medicine.

Doses depend on age, weight, kidney and liver function and other medicines, so the assistant
refers people to their doctor or pharmacist. This is enforced in code on the finished answer
(in `answer_question` and again in the graph's output guard), not only in the prompt: a model
can be wrong, or be talked into quoting a number from its context.

What counts: a number with a medicine unit (mg, mcg/µg, IU, units, ml, "drops") or with a
dosage form ("2 tablets", "one capsule", "eine Tablette"). What does not: lab values and
measurements such as "100 mg/dL", "A1C 6.5%", "7 to 9 hours of sleep".

Trade-off, stated honestly: the guard prefers a false alarm to a missed dose. An answer that
quotes a nutrient amount ("less than 2,300 mg of sodium") is replaced too. Plain grams ("4 g")
are not matched because they are mostly food quantities; the prompt rule covers those.
"""

import re

from medagent.guardrails.texts import EN

_NUMBER = r"\d+(?:[.,]\d+)?"
_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|half(?: an?)?"
    r"|a couple of|a few|einen?|eine?|zwei|drei|vier|f(?:ü|ue)nf|sechs|acht|zehn|halbe?)"
)
_FORM = (
    r"(?:tablets?|pills?|capsules?|caplets?|drops?|puffs?|sprays?|teaspoons?|tablespoons?"
    r"|sachets?|patch(?:es)?|suppositor(?:y|ies)|injections?|tabletten?|pillen?|kapseln?|tropfen"
    r"|tabl\.|tee-?l(?:ö|oe)ffel|ess-?l(?:ö|oe)ffel|z(?:ä|ae)pfchen|beutel|pflaster|h(?:ü|ue)be?"
    r"|spritzen?|ampullen?|dragees?)"
)
_UNIT = (
    r"(?:mg|mcg|µg|μg|iu|i\.u\.|units?|einheiten|ml|milligrams?|micrograms?|milligramm"
    r"|mikrogramm|milliliters?|millilitern?|drops?|tropfen)"
)

_DOSE = re.compile(
    rf"(?<![\w/.,]){_NUMBER}\s?{_UNIT}(?![\w/])"  # "400 mg", "5 ml" ... but not "100 mg/dL"
    rf"|(?<![\w/.,]){_NUMBER}\s?(?:-|\u2013|to|bis)\s?{_NUMBER}\s?{_UNIT}(?![\w/])"  # "200-400 mg"
    rf"|\b(?:{_NUMBER}|{_NUMBER_WORD})\s+{_FORM}\b"  # "2 tablets", "one capsule", "zwei Tabletten"
    r"|\b(?:a|one|1)\s+(?:single\s+)?(?:teaspoon|tablespoon)\b"
    r"|\b(?:ein|einen|1)\s+(?:einzelnen?\s+)?(?:tee|ess)-?l(?:ö|oe)ffel\b",
    re.IGNORECASE,
)

DOSE_REFERRAL = EN.dose_referral  # the German one is in texts.py


def contains_dose(text: str) -> bool:
    """True if the text states a specific dose or quantity of a medicine."""
    return _DOSE.search(text) is not None
