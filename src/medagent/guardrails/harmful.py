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
        r"\bwie\s?viel\w*\b.{0,60}\b(?:sind|ist|w(?:ä|ae)re|w(?:ä|ae)ren)\s+"
        r"(?:t(?:ö|oe)dlich|letal)",
        r"\bso (?:that )?i (?:don'?t|do not|never) wake up\b",
        r"\bdosis\b.{0,25}\b(?:t(?:ö|oe)dlich|letal)",
        # German
        r"\b(?:t(?:ö|oe)dlich|letal)\w*\s+(?:dosis|dosierung|menge)\b",
        r"\bwie\s?(?:viele?|viel)\b.{0,60}\b(?:um|damit|bis)\b.{0,30}"
        r"\b(?:zu sterben|sterben|stirbt|sterbe|t(?:ö|oe)ten|umzubringen|umbringen|zu vergiften"
        r"|vergiften|tot)\b",
        r"\bgenug\b.{0,40}\b(?:um zu sterben|zum sterben|um mich umzubringen)\b",
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
        r"\b(?:spike|lace)\b.{0,25}\b(?:drink|food|coffee|tea|meal|water)\b",
        r"\bto make (?:someone|somebody|a person|him|her|them|people) (?:very |really |seriously"
        r" |extremely )?(?:sick|ill|unwell|pass out|unconscious)\b",
        rf"\bmake\s+{_GAP}{_PERSON_EN}\s+(?:very |really |seriously )?(?:ill|sick|unwell)\b",
        r"\b(?:look|appear|seem)\s+like\s+(?:natural causes|an accident|suicide)\b",
        rf"\bget rid of\s+{_GAP}{_PERSON_EN}\b.{{0,20}}\b(?:permanently|for good)\b",
        r"\bnicht mehr aufwach\w*",
        r"\bput (?:something|poison|drugs?|pills?)\b.{0,15}\bin\b.{0,25}\b(?:drink|food|coffee"
        r"|tea|meal|water)\b",
        # German
        rf"\bwie (?:kann|k(?:ö|oe)nnte|soll|muss|w(?:ü|ue)rde)\s+ich\s+.{{0,25}}\b{_PERSON_DE}\b"
        rf".{{0,25}}\b{_HARM_VERB_DE}\b",
        # (up to two words may sit in between: "jemanden unbemerkt umbringen")
        rf"\b{_PERSON_DE}\s+(?:\w+\s+){{0,2}}(?:zu\s+)?{_HARM_VERB_DE}\b",
        r"\b(?:gift|substanz|mittel)\b.{0,30}\b(?:nicht nachweisbar|nicht auff(?:ä|ae)llt"
        r"|unauff(?:ä|ae)llig|nicht erkennbar|spurlos)\b",
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
        r"\b(?:schmerzlos|schmerzfrei|sanft|schnell)\w*\s+(?:weg|methode|art)\s+"
        r"(?:zu sterben|sich umzubringen|sich das leben zu nehmen)",
    ],
}

_COMPILED = {
    kind: [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]
    for kind, patterns in _PATTERNS.items()
}

HARMFUL_MESSAGE = (
    "I'm sorry, but I can't help with that, and I'm not able to give information about it.\n\n"
    "If you are thinking about ending your life or hurting yourself, you don't have to carry "
    "this alone. Please reach out right now:\n"
    "- Germany: TelefonSeelsorge, free and anonymous, 24/7: 0800 111 0 111\n"
    "- EU: 112 (emergency services)\n"
    "- US: call or text 988 (Suicide & Crisis Lifeline)\n\n"
    "If you are worried you might hurt someone else, please call 112 or talk to a doctor or "
    "someone you trust today.\n\n"
    "If someone has accidentally swallowed something dangerous, call 112 right away, or your "
    "local poison control centre (Giftnotruf in Germany; Poison Help 1-800-222-1222 in the US).\n\n"
    "I'm happy to help with other health questions, finding a doctor, or booking an appointment."
)


@dataclass(frozen=True, slots=True)
class HarmfulFlag:
    kind: str  # "lethal_dose" | "harm_to_others" | "self_harm_method" (for logs; never the text)
    matched: str  # the matched phrase from the user's own text; never logged


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def detect_harmful_intent(text: str) -> HarmfulFlag | None:
    """Return the first harmful-intent pattern found in the message, or None."""
    normalised = _normalise(text)
    for kind, patterns in _COMPILED.items():
        for pattern in patterns:
            match = pattern.search(normalised)
            if match:
                return HarmfulFlag(kind=kind, matched=match.group(0))
    return None
