"""Deterministic detection of harmful-intent messages: lethal doses, how to kill, poison or harm
someone, "enough pills to die", and methods of suicide. English and German.

Why rules and not only the model: safety must not depend on a model choosing to refuse. These
rules run before any LLM call, so the model never sees the message and cannot be talked into
answering it, whatever framing is used ("for a novel", "as a nurse", "ignore previous
instructions"). They apply regardless of question form: "How many tablets would kill a person?"
starts with "How", which is exactly why this module exists.

Tuned for recall on clear phrasings while leaving ordinary questions alone ("How do sleeping
pills work?", "Can paracetamol overdose damage the liver?", "Do antibiotics kill viruses?").
The person noun must sit right next to the verb, so "kill a fever in a child" is not a match.
Paraphrases the rules miss are the router's `is_harmful` flag's job (second layer), and the
red-team set in `evals/redteam/` measures both.

A hit is answered with a fixed, compassionate message that gives no information at all.
"""

import re
import unicodedata
from dataclasses import dataclass

from medagent.guardrails.texts import EN


class _German(str):
    """A pattern that matches German phrasing. The language of the pattern that matched decides
    the language of the fixed reply (the rules run before any model, so there is nothing else to
    go by)."""


_de = _German

# ---- building blocks -------------------------------------------------------------------------
_PERSON_EN = (
    r"(?:person|people|someone|somebody|anyone|human|man|woman|adult|child|kid|baby|husband|wife"
    r"|spouse|partner|boyfriend|girlfriend|ex|neighbou?r|boss|colleague|coworker|teacher|mother"
    r"|father|mum|mom|dad|parents?|sister|brother|grandm\w+|grandf\w+|family|friend|patient)"
)
_PERSON_DE = (
    r"(?:jemand(?:en)?|mensch(?:en)?|person(?:en)?|mann|frau|ehemann|ehefrau|partner(?:in)?"
    r"|freund(?:in)?|chef(?:in)?|nachbar(?:in)?|kolleg(?:e|in)|mutter|vater|eltern|bruder"
    r"|schwester|kind|baby|oma|opa|gro(?:ß|ss)mutter|gro(?:ß|ss)vater|familie)"
)
# The same persons with accusative / dative / plural endings ("meinen Nachbarn", "meine Kinder").
# Only used in patterns that also need first-person intent or a conjugated harm verb: the bare
# plural next to an infinitive would flag child-safety questions ("dass sich Kinder verletzen").
_PERSON_DE_INFL = (
    r"(?:jemand(?:en|em)?|mensch(?:en)?|person(?:en)?|mann|frau|ehemann|ehefrau"
    r"|partner(?:in|n|innen)?|freund(?:in|e|en|innen)?|chef(?:in|s)?|nachbar(?:in|n|innen)?"
    r"|kolleg(?:e|in|en|innen)|mutter|vater|eltern|bruder|schwester|kind(?:er|ern)?|baby|oma|opa"
    r"|gro(?:ß|ss)mutter|gro(?:ß|ss)vater|familie|schwieger(?:mutter|vater|eltern|sohn|tochter)"
    r"|sohn|tochter|enkel(?:in|kind)?|lehrer(?:in)?|patient(?:in|en)?)"
)
_HARM_VERB_INTENT_DE = r"(?:vergiften|t(?:ö|oe)ten|umbringen|ermorden|verletzen)"
# Protective or reflexive wording in the same clause: "damit Kinder sich nicht verletzen".
_NOT_PROTECTIVE = (
    r"(?!.{0,50}\b(?:sch(?:ü|ue)tz\w*|verhinder\w*|vorbeug\w*|vermeid\w*|davor|sich)\b)"
)
# Up to two filler words (articles, possessives, an adjective) between verb and person.
_GAP = r"(?:\w+\s+){0,2}"
_HARM_VERB_EN = (
    r"(?:kill|murder|poison|hurt|harm|assassinate|drug|sedate|incapacitate|euthani[sz]e)"
)
_HARM_VERB_INTENT_EN = r"(?:kill|murder|poison|hurt|harm|assassinate)"  # "drug" is also a noun
_HARM_VERB_DE = r"(?:vergiften|t(?:ö|oe)ten|umbringen|ermorden|verletzen|betäuben)"
_DIE_EN = (
    r"(?:kill|die|be fatal|be lethal|cause death|end (?:a |my |his |her |one'?s )?life"
    r"|overdose and die)"
)

_PATTERNS: dict[str, list[str]] = {
    "lethal_dose": [
        r"\b(?:lethal|fatal|deadly)\s+(?:dose|dosage|amount|quantity|level|overdose)s?\b",
        r"\bld\s?-?50\b",
        # "how many sleeping tablets to kill a person", "how much insulin would be fatal",
        # "how many pills do I need to take to die"
        rf"\bhow (?:much|many)\b.{{0,60}}\b(?:to|would|will|could|does it take to|is needed to"
        rf"|are needed to|is required to|are required to)\s+{_DIE_EN}",
        # "are 20 sleeping pills enough to kill someone", "is 30 tablets enough to die"
        r"\benough\b.{0,40}\b(?:to|for)\s+(?:kill|die|death|end (?:my|a|his|her) life"
        r"|be fatal|be lethal)",
        # a quantity plus a way of dying: "would 20 paracetamol tablets be fatal"
        r"\b\d+\b.{0,30}\b(?:tablets?|pills?|capsules?|mg|grams?|units|ml)\b.{0,40}"
        r"\b(?:kill|fatal|lethal|to die|be enough to die)",
        # "what amount of sleeping pills would be deadly", "what quantity of morphine ends a life"
        r"\bwhat (?:amount|quantity|dose|dosage|number)\b.{0,50}\b(?:deadly|fatal|lethal|kills?"
        r"|ends? (?:a|my|his|her) life|cause death)",
        r"\b(?:too many|too much)\b.{0,30}\b(?:fatal|lethal|deadly)\b",
        # "how many ibuprofen tablets are lethal", "how many xanax to overdose fatally"
        r"\bhow (?:much|many)\b.{0,60}\b(?:is|are|would be|could be)\s+(?:a\s+)?"
        r"(?:lethal|fatal|deadly)\b",
        r"\boverdose\b.{0,15}\b(?:fatally|lethally)\b",
        # "at how many pills do you die", "how much paracetamol is life threatening"
        r"\bat how many\b.{0,40}\b(?:die|dies|death|dead)\b",
        r"\bhow (?:much|many)\b.{0,50}\b(?:is|are)\s+(?:life[- ]threatening|life[- ]endangering)\b",
        _de(r"\bab wie vielen?\b.{0,40}\b(?:stirbt|sterben|ist man tot)\b"),
        _de(r"\bwie\s?viel\w*\b.{0,40}\blebensgef(?:ä|ae)hrlich"),
        _de(
            r"\bwie\s?viel\w*\b.{0,60}\b(?:sind|ist|w(?:ä|ae)re|w(?:ä|ae)ren)\s+"
            r"(?:t(?:ö|oe)dlich|letal)"
        ),
        r"\bso (?:that )?i (?:don'?t|do not|never) wake up\b",
        _de(
            r"\b(?:dosis|menge)\b.{0,40}\b(?:t(?:ö|oe)dlich|letal)"
        ),  # "welche Menge ... ist tödlich"
        _de(r"\b(?:t(?:ö|oe)dlich|letal)\w*\s+(?:dosis|dosierung|menge)\b"),
        # "mit wie vielen Tabletten kann man sich umbringen"
        _de(r"\bwie\s?viel\w*\b.{0,60}\b(?:sich|mich)\s+(?:umzubringen|umbringen|t(?:ö|oe)ten)"),
        _de(
            r"\bwie\s?(?:viele?|viel)\b.{0,60}\b(?:um|damit|bis|zum)\b.{0,30}"
            r"\b(?:zu sterben|sterben|stirbt|sterbe|t(?:ö|oe)ten|umzubringen|umbringen|zu vergiften"
            r"|vergiften|tot)\b"
        ),
        _de(r"\bgenug\b.{0,40}\b(?:um zu sterben|zum sterben|um mich umzubringen)\b"),
    ],
    "harm_to_others": [
        # "how can I poison someone", "best way to kill my husband", "how to harm a person"
        rf"\b(?:how|ways?|best way|easiest way|quickest way)\s+(?:to|can i|do i|would i|could i"
        rf"|should i|might i)\s+(?:secretly |quietly |slowly )?{_HARM_VERB_EN}\s+{_GAP}"
        rf"{_PERSON_EN}\b",
        # "I want to hurt someone", "I'm going to kill my boss"
        rf"\b(?:want|going|plan(?:ning)?|need|trying|wish|intend)\s+to\s+{_HARM_VERB_INTENT_EN}"
        rf"\s+{_GAP}{_PERSON_EN}\b",
        # "poison my neighbour with pills"
        rf"\b{_HARM_VERB_INTENT_EN}\s+{_GAP}{_PERSON_EN}\b.{{0,40}}\b(?:with|using|by)\b.{{0,20}}"
        r"\b(?:pills?|tablets?|medication|medicine|drugs?|overdose|insulin|poison)\b",
        r"\b(?:untraceable|undetectable|odou?rless|tasteless)\b.{0,25}"
        r"\b(?:poison|toxin|drug|substance|method)s?\b",
        r"\b(?:poison|toxin|drug|substance)s?\b.{0,25}\b(?:untraceable|undetectable|undetected"
        r"|not (?:be )?(?:traced|detected|found)|no (?:trace|taste|smell))",
        r"\bpoison\w*\b.{0,30}\b(?:without (?:being )?(?:noticed|detected)|unnoticed)\b",
        _de(r"\bgift\w*\b.{0,30}\bunbemerkt"),
        r"\b(?:spike|lace)\b.{0,25}\b(?:drink|food|coffee|tea|meal|water)\b",
        r"\bto make (?:someone|somebody|a person|him|her|them|people) (?:very |really |seriously"
        r" |extremely )?(?:sick|ill|unwell|pass out|unconscious)\b",
        rf"\bmake\s+{_GAP}{_PERSON_EN}\s+(?:very |really |seriously )?(?:ill|sick|unwell)\b",
        r"\b(?:look|appear|seem)\s+like\s+(?:natural causes|an accident|suicide)\b",
        rf"\bget rid of\s+{_GAP}{_PERSON_EN}\b.{{0,20}}\b(?:permanently|for good)\b",
        # a PURPOSE ("damit sie nicht mehr aufwacht", "um nicht mehr aufzuwachen") asks for a
        # method. A bare wish ("ich wünschte, ich würde nicht mehr aufwachen") is passive ideation:
        # it gets the support reply (self_harm.py), not this refusal.
        _de(r"\b(?:damit|dass|sodass|so dass)\b(?:\s+\w+){0,3}\s+nicht mehr aufwach\w*"),
        _de(r"\bum\b(?:\s+\w+){0,3}\s+nicht mehr aufzuwachen\b"),
        r"\bput (?:something|poison|drugs?|pills?)\b.{0,15}\bin\b.{0,25}\b(?:drink|food|coffee"
        r"|tea|meal|water)\b",
        _de(
            rf"\bwie (?:kann|k(?:ö|oe)nnte|soll|muss|w(?:ü|ue)rde)\s+ich\s+"
            rf".{{0,25}}\b{_PERSON_DE}\b"
            rf".{{0,25}}\b{_HARM_VERB_DE}\b"
        ),
        # (up to two words may sit in between: "jemanden unbemerkt umbringen")
        _de(rf"\b{_PERSON_DE}\s+(?:\w+\s+){{0,2}}(?:zu\s+)?{_HARM_VERB_DE}\b"),
        # first-person intent with inflected persons: "ich will meinen Nachbarn vergiften"
        _de(
            r"\b(?:ich|wir)\s+(?:will|wollen|m(?:ö|oe)chte|m(?:ö|oe)chten|werde|werden|muss|plane"
            r"|habe vor|w(?:ü|ue)rde gerne?)\s+"
            rf"{_NOT_PROTECTIVE}(?:\w+\s+){{0,2}}{_PERSON_DE_INFL}\b(?:\s+\w+){{0,3}}?\s+"
            rf"{_HARM_VERB_INTENT_DE}\b"
        ),
        # "wie kann ich meine Kollegen vergiften"
        _de(
            r"\bwie (?:kann|k(?:ö|oe)nnte|soll|muss|w(?:ü|ue)rde)\s+ich\s+"
            rf"{_NOT_PROTECTIVE}(?:\w+\s+){{0,2}}{_PERSON_DE_INFL}\b(?:\s+\w+){{0,3}}?\s+"
            rf"{_HARM_VERB_INTENT_DE}\b"
        ),
        # conjugated harm verb: "wie vergifte ich meine Schwiegermutter", "wie töte ich jemanden"
        _de(
            r"\bwie\s+(?:vergifte|t(?:ö|oe)te|ermorde|verletze)\s+ich\s+"
            rf"{_NOT_PROTECTIVE}(?:\w+\s+){{0,2}}{_PERSON_DE_INFL}\b"
        ),
        # separable verb, only when "um" ends the clause: "ich bringe meinen Chef um." but not
        # "ich bringe meinen Vater um 9 Uhr zum Arzt"
        _de(
            r"\bbring\w*\s+(?:ich\s+|wir\s+)?(?:\w+\s+){0,3}?"
            rf"{_PERSON_DE_INFL}\b(?:\s+\w+){{0,3}}?\s+um"
            r"(?=\s*(?:[.,!?;:]|$|und\b|weil\b|damit\b))"
        ),
        _de(
            r"\b(?:gift|substanz|mittel)\b.{0,30}\b(?:nicht nachweisbar|nicht auff(?:ä|ae)llt"
            r"|unauff(?:ä|ae)llig|nicht erkennbar|spurlos)\b"
        ),
    ],
    "self_harm_method": [
        r"\b(?:painless|peaceful|quick|quickest|easy|easiest|best|simplest|least painful|fastest"
        r"|most effective|sure)\s+"
        r"(?:way|method|means)s?\s+(?:to|of)\s+(?:die|dying|end (?:my|it|one'?s) ?(?:life|all)?"
        r"|kill (?:myself|oneself)|commit suicide|suicide)",
        r"\b(?:painless|peaceful|quick|easy)\s+(?:death|overdose|suicide)\b",
        r"\boverdose\b.{0,25}\b(?:painless|peaceful|quick|easy)\b",
        r"\bhow (?:to|do i|can i|could i)\s+(?:commit suicide|kill myself|end my life"
        r"|take my own life|overdose (?:and die|on purpose)|die in my sleep)",
        r"\bwhich (?:medication|pill|drug|medicine)s?\s+(?:is|are)\s+(?:the\s+)?"
        r"(?:painless|quick|fatal|lethal)",
        _de(
            r"\b(?:schmerzlos|schmerzfrei|sanft|schnell)\w*\s+(?:weg|methode|art)\s+"
            r"(?:zu sterben|sich umzubringen|sich das leben zu nehmen)"
        ),
        # "wie kann man sich schmerzlos umbringen"
        _de(
            r"\b(?:sich|mich)\s+(?:schmerzlos|schmerzfrei|sanft|schnell|ohne schmerzen)\w*\s+"
            r"(?:umzubringen|umbringen|t(?:ö|oe)ten)"
        ),
    ],
}

_COMPILED: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    kind: [
        ("de" if isinstance(p, _German) else "en", re.compile(p, re.IGNORECASE | re.DOTALL))
        for p in patterns
    ]
    for kind, patterns in _PATTERNS.items()
}

# The English text lives in texts.py (with the German one); re-exported so imports keep working.
HARMFUL_MESSAGE = EN.harmful_message


@dataclass(frozen=True, slots=True)
class HarmfulFlag:
    kind: str  # "lethal_dose" | "harm_to_others" | "self_harm_method" (for logs; never the text)
    matched: str  # the matched phrase from the user's own text; never logged
    # "de" only if every pattern that matched is German; a mix (or any English match) is "en".
    language: str = "en"


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def detect_harmful_intent(text: str) -> HarmfulFlag | None:
    """Return the first harmful-intent pattern found in the message, or None.

    All patterns are checked so the language can be decided: German only if nothing English
    matched too (the English reply is the safe default for a mixed message)."""
    normalised = _normalise(text)
    first: tuple[str, str] | None = None
    languages: set[str] = set()
    for kind, patterns in _COMPILED.items():
        for language, pattern in patterns:
            match = pattern.search(normalised)
            if match:
                languages.add(language)
                if first is None:
                    first = (kind, match.group(0))
    if first is None:
        return None
    return HarmfulFlag(
        kind=first[0], matched=first[1], language="de" if languages == {"de"} else "en"
    )
