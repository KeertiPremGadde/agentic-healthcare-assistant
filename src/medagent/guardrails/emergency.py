"""Deterministic red-flag detection: the first safety layer, before any LLM call.

Why rules and not only the LLM: an emergency answer must not depend on an API being up, a model
following instructions, or a prompt being injected. Rules are fast, free, testable and auditable.
The router's `is_emergency` flag is the second layer for phrasings the rules miss.

Tuned for recall over precision: a false alarm costs one extra message ("if this is not acute,
I can help you book..."); a missed emergency is the failure that matters. English is the main
language; common German phrasings are covered because the clinic is in Germany.

General questions with no person involved ("what are the signs of a stroke?") are *not*
short-circuited: they are answered, with a safety notice in front.
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedFlag:
    category: str
    matched: str  # the matched phrase (from the user's own text; never logged)
    # True for a general question with no person involved: answer it with a safety notice.
    # False => someone may be affected now: short-circuit to the emergency response.
    informational: bool = False


_PATTERNS: dict[str, list[str]] = {
    "cardiac": [
        r"chest pains?",
        r"pain in (?:my|the|his|her) chest",
        r"heart attack",
        r"crushing (?:pain|pressure)",
        r"brustschmerz\w*",
        r"schmerzen in der brust",
        r"herzinfarkt",
        r"engegefühl in der brust",
    ],
    "breathing": [
        r"(?:can ?not|can'?t|cannot|unable to) breathe?",
        r"(?:struggling|hard|difficult(?:y)?) (?:to )?breath(?:e|ing)",
        r"short(?:ness)? of breath",
        r"not breathing",
        r"choking",
        r"atemnot",
        r"keine luft",
        r"(?:kann|bekomme) (?:nicht|kaum) (?:mehr )?atmen",
        r"erstick\w*",
    ],
    "stroke": [
        r"stroke",
        r"face (?:is )?droop\w*",
        r"slurred speech",
        r"(?:sudden(?:ly)?|one side).{0,30}(?:numb|weak|paraly[sz]ed)",
        r"schlaganfall",
        r"hängender mundwinkel",
        r"lähmung\w*",
        r"sprachstörung\w*",
    ],
    "self_harm": [
        r"kill (?:myself|me)",
        r"suicid\w*",
        r"end (?:my life|it all)",
        r"(?:want|going) to die",
        r"self[- ]?harm",
        r"hurt(?:ing)? myself",
        r"suizid\w*",
        r"selbstmord\w*",
        r"(?:mich|mir) (?:umbringen|das leben nehmen)",
        r"nicht mehr leben",
    ],
    "unconscious": [
        r"unconscious",
        r"passed out",
        r"(?:won'?t|not) wak(?:e|ing) up",
        r"unresponsive",
        r"bewusstlos\w*",
        r"ohnmächtig",
        r"nicht ansprechbar",
    ],
    "bleeding": [
        r"(?:heavy|severe|uncontrolled) bleeding",
        r"bleeding (?:heavily|a lot|won'?t stop)",
        r"vomiting blood",
        r"starke blutung\w*",
        r"blutet stark",
        r"blut erbrechen",
    ],
    "anaphylaxis": [
        r"anaphyla\w*",
        r"(?:throat|tongue|lips?) (?:is |are )?swell\w*",
        r"allergic reaction.{0,30}breath",
        r"allergischer schock",
        r"zunge schwillt",
    ],
    "overdose_poisoning": [
        r"overdos\w*",
        r"poison\w*",
        r"swallowed (?:bleach|pills)",
        r"überdosis",
        r"vergift\w*",
    ],
    "seizure": [
        r"seizure",
        r"convuls\w*",
        r"krampfanfall",
        r"epileptischer anfall",
    ],
}

_COMPILED = {
    category: re.compile(r"\b(?:" + "|".join(patterns) + r")", re.IGNORECASE)
    for category, patterns in _PATTERNS.items()
}

# Someone is (or may be) affected: first person, a third person, or a relative.
_PERSON = re.compile(
    r"\b(?:i|i'm|im|i've|me|my|mine|we|our|us|he|she|him|her|they|them|someone|somebody|"
    r"husband|wife|son|daughter|child|baby|mum|mom|dad|mother|father|friend|"
    r"ich|mir|mich|mein\w*|wir|uns|er|ihm|jemand|kind|mutter|vater|mann|frau)\b",
    re.IGNORECASE,
)
# A general question: starts with a question word, "tell me" or "explain".
_QUESTION_START = re.compile(
    r"^(?:what|how|why|which|when|is|are|can|does|do|tell me|explain|define|"
    r"was|wie|warum|welche\w*|wann|ist|sind|erklär\w*)\b",
    re.IGNORECASE,
)

EMERGENCY_MESSAGE = (
    "This may be a medical emergency. Please call emergency services now: 112 in Germany and the "
    "EU (Notruf 112), 911 in the US. If someone is unconscious or not breathing, call immediately "
    "and follow the dispatcher's instructions. For thoughts of suicide or self-harm in Germany you "
    "can also call the TelefonSeelsorge on 0800 111 0 111 (free, 24/7).\n\n"
    "I can't assess emergencies. If this is not acute, tell me and I can help you find a doctor "
    "or book an appointment."
)

SAFETY_NOTICE = (
    "If you or someone near you has these symptoms right now, call emergency services "
    "(112 in Germany/EU, 911 in the US)."
)


def _normalise(text: str) -> str:
    # NFC so composed and decomposed umlauts match the same pattern; collapse whitespace.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _is_informational(text: str) -> bool:
    return bool(_QUESTION_START.search(text)) and not _PERSON.search(text)


def detect_red_flag(text: str) -> RedFlag | None:
    """Return the first red flag found in the user's message, or None."""
    normalised = _normalise(text)
    for category, pattern in _COMPILED.items():
        match = pattern.search(normalised)
        if match:
            return RedFlag(category, match.group(0), informational=_is_informational(normalised))
    return None
