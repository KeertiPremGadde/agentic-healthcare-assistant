"""Dose guard: a medical answer must never contain a specific dose or quantity of a medicine.

Doses depend on age, weight, kidney and liver function and other medicines, so the assistant
refers people to their doctor or pharmacist. This is enforced in code on the finished answer
(in `answer_question` and again in the graph's output guard), not only in the prompt: a model
can be wrong, or be talked into quoting a number from its context.

What counts: a number with a medicine unit (mg, mcg/µg, IU, units, ml, "drops") or with a
dosage form ("2 tablets", "one capsule", "eine Tablette"). What does not: lab values and
measurements such as "100 mg/dL", "A1C 6.5%", "7 to 9 hours of sleep".

Also counted (ADR 0022): amounts per kilogram, per day, per dose or per hour ("10 mg/kg",
"0.5 mg/kg/day", "25 mcg/h", "40 mg/day": a slash after the unit used to hide them, to keep
"100 mg/dL" out), and grams ("4 g per day", "one gram", "4 Gramm"). Grams are also food, so a
sentence about nutrition ("25 g of fiber a day", "a 100 g serving") is left alone unless it also
talks about taking a medicine. "g/dL" and "g/L" stay lab values.

Trade-off, stated honestly: the guard prefers a false alarm to a missed dose. An answer that
quotes a nutrient amount ("less than 2,300 mg of sodium") is replaced too, and so is a gram amount
of a food the nutrition words below do not recognise.
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

# An amount per body weight, day, dose or hour: "10 mg/kg", "0.5 mg/kg/day", "25 mcg/h",
# "40 mg/day",
# "10 mg pro kg". The denominator must end the word, so "mg/dL" (d + L) is still a lab value.
_RATE = re.compile(
    rf"(?<![\w/.,]){_NUMBER}\s?(?:mg|mcg|µg|μg|ml|iu|units?|einheiten)\s?(?:/|per|pro|je)\s?"
    r"(?:kg|kilo\w*|day|d|dose|h|hr|hour|min|minute|tag)(?!\w)",
    re.IGNORECASE,
)
# Grams: "4 g", "4 grams", "4 Gramm", "one gram". Not "g/dL" or "g/L" (lab values), and not
# "gram-negative".
_GRAMS = re.compile(
    rf"(?<![\w/.,])(?:{_NUMBER}\s?(?:g|grams?|gramm)|{_NUMBER_WORD}\s+(?:grams?|gramm))"
    r"(?![\w-])(?!\s?/\s?(?:dl|l)(?!\w))",
    re.IGNORECASE,
)
_NUTRITION = re.compile(
    r"\b(?:fib(?:er|re)|protein\w*|fat|fats|sugars?|salt|carbs|carbohydrates?|calories|kcal|diet"
    r"|nutrition|nutrients?|food|foods|eat|eating|ate|meal|serving|portion|snack|nuts|rice"
    r"|ballaststoff\w*|salz|zucker|eiwei(?:ß|ss)|kohlenhydrat\w*|kalorien|ern(?:ä|ae)hrung"
    r"|mahlzeit|reis|n(?:ü|ue)sse|essen)\b",
    re.IGNORECASE,
)
_MEDICINE = re.compile(
    r"\b(?:take|takes|taking|taken|give|given|giving|dose|doses|dosing|dosage|administer\w*"
    r"|medicine|medication|drug|tablets?|pills?|capsules?|syrup|infusion|injection|paracetamol"
    r"|acetaminophen|ibuprofen|aspirin|nehmen|nehmt|einnehmen|nimm\w*|geben|dosis|dosierung"
    r"|medikament\w*|arznei\w*|tabletten?|kapseln?)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")

DOSE_REFERRAL = EN.dose_referral  # the German one is in texts.py


def _gram_dose(text: str) -> bool:
    """A gram amount that is not food: a nutrition sentence is exempt unless it mentions taking a
    medicine, so "take 4 g of paracetamol with food" is still caught."""
    for sentence in _SENTENCE.split(text):
        if _GRAMS.search(sentence) and (
            _MEDICINE.search(sentence) or not _NUTRITION.search(sentence)
        ):
            return True
    return False


def contains_dose(text: str) -> bool:
    """True if the text states a specific dose or quantity of a medicine."""
    return _DOSE.search(text) is not None or _RATE.search(text) is not None or _gram_dose(text)
