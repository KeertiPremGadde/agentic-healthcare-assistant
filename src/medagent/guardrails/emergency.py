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

from medagent.guardrails.texts import EN, texts_for


class _German(str):
    """A pattern that matches German phrasing. The language of the pattern that matched decides
    the language of the fixed reply (the rules run before any model, so there is nothing else to
    go by)."""


_de = _German


@dataclass(frozen=True, slots=True)
class RedFlag:
    category: str
    matched: str  # the matched phrase (from the user's own text; never logged)
    # True for a general question with no person involved: answer it with a safety notice.
    # False => someone may be affected now: short-circuit to the emergency response.
    informational: bool = False
    # "de" only if every pattern that matched is German; a mix (or any English match) is "en".
    language: str = "en"


def _language_of(pattern: str) -> str:
    return "de" if isinstance(pattern, _German) else "en"


_PATTERNS: dict[str, list[str]] = {
    "cardiac": [
        r"chest pains?",
        r"pain in (?:my|the|his|her) chest",
        r"heart attack",
        r"crushing (?:pain|pressure)",
        _de(r"brustschmerz\w*"),
        _de(r"schmerzen (?:in|auf) (?:\w+ ){0,2}brust\b"),  # der / meiner / der linken Brust
        _de(r"herzinfarkt"),
        _de(r"engegefühl (?:in|auf) (?:\w+ ){0,2}brust\b"),
    ],
    "breathing": [
        r"(?:can ?not|can'?t|cannot|unable to) breathe?",
        r"(?:struggling|hard|difficult(?:y)?) (?:to )?breath(?:e|ing)",
        r"short(?:ness)? of breath",
        r"not breathing",
        r"choking",
        _de(r"atemnot"),
        _de(r"keine luft"),
        _de(
            r"(?:bekomm\w*|kriegt|kriege)\s+(?:kaum|nicht genug|nicht mehr|schlecht)"
            r"(?:\s+noch)?\s+luft"
        ),
        _de(r"(?:kann|können|konnte)\s+(?:nicht|kaum)(?:\s+(?:mehr|noch))*\s+atmen"),
        # "atmet nicht mehr", but not a blocked nose ("atmet nicht durch die Nase")
        _de(r"atmet\s+(?:nicht|kaum)\b(?!\s+(?:durch|mit)\b)"),
        _de(r"erstick\w*"),
    ],
    "stroke": [
        r"stroke",
        r"face (?:is )?droop\w*",
        r"slurred speech",
        r"(?:sudden(?:ly)?|one side).{0,30}(?:numb|weak|paraly[sz]ed)",
        _de(r"schlaganfall"),
        # "hängender Mundwinkel", "der Mundwinkel hängt", "bei ihm hängt der Mundwinkel herunter"
        _de(r"h(?:ä|ae)ng\w*\s+(?:\w+\s+){0,2}mundwinkel|mundwinkel\s+h(?:ä|ae)ng\w*"),
        _de(r"lähmung\w*"),
        _de(r"gel(?:ä|ae)hmt\w*"),
        _de(r"sprachstörung\w*"),
    ],
    "self_harm": [
        r"kill (?:myself|me)",
        r"suicid\w*",
        r"end (?:my life|it all)",
        r"(?:want|going) to die",
        r"(?:don'?t|do not|no longer) want to (?:live|be alive|go on)",
        r"better off dead",
        r"(?:wish|wished) i (?:was|were) dead",
        r"self[- ]?harm",
        r"hurt(?:ing)? myself",
        _de(r"suizid\w*"),
        _de(r"selbstmord\w*"),
        _de(r"(?:mich|sich)\s+(?:selbst\s+)?(?:umzubringen|umbringen|t(?:ö|oe)ten)"),
        # "mir das Leben nehmen", "sich das Leben genommen", "sich das Leben zu nehmen"
        _de(r"(?:mir|mich|sich)\s+(?:\w+\s+){0,2}das\s+leben\s+(?:zu\s+)?(?:nehmen|genommen)"),
        # word order of questions and main clauses: "nehme ich mir das Leben", "er nimmt sich ..."
        _de(r"(?:nehm\w*|nimm\w*)\s+(?:\w+\s+)?(?:mir|sich|mich)\s+das\s+leben"),
        # separable verb, only when "um" ends the clause: "ich bringe mich um." but not
        # "ich bringe mich um 8 Uhr zur Praxis"
        _de(
            r"bring\w*\s+(?:ich\s+)?(?:mich|sich)\s+(?:\w+\s+){0,3}um"
            r"(?=\s*(?:[.,!?;:]|$|und\b|weil\b|damit\b))"
        ),
        _de(r"nicht mehr leben"),
    ],
    "unconscious": [
        r"unconscious",
        r"passed out",
        r"(?:won'?t|not) wak(?:e|ing) up",
        r"unresponsive",
        _de(r"bewusstlos\w*"),
        _de(r"ohnm(?:ä|ae)chtig\w*"),
        # "in Ohnmacht gefallen", not the feeling of powerlessness ("Gefühl der Ohnmacht")
        _de(r"in ohnmacht (?:gefallen|fallen|f(?:ä|ae)llt|sinken|sank)|ohnmachtsanfall\w*"),
        _de(r"nicht (?:mehr )?ansprechbar"),
        # "wacht nicht mehr auf" (not "wacht nachts nicht mehr auf": a child sleeping through)
        _de(r"wach(?:t|te|en)\s+nicht(?:\s+mehr)?\s+auf\b"),
    ],
    "bleeding": [
        r"(?:heavy|severe|uncontrolled) bleeding",
        r"bleeding (?:heavily|a lot|won'?t stop)",
        r"vomiting blood",
        _de(r"starke blutung\w*"),
        _de(r"blutet\s+(?:\w+\s+)?stark"),
        _de(r"stark\w*\s+blutend\w*"),
        _de(r"blut erbrechen"),
        # "erbricht Blut", "hat Blut erbrochen"
        _de(r"(?:erbricht|erbrach|erbrochen)\s+(?:\w+\s+)?blut\b|blut\s+(?:\w+\s+)?erbrochen"),
    ],
    "anaphylaxis": [
        # English spellings only: "anaphylaxis", "anaphylactic". The German "Anaphylaxie" and
        # "anaphylaktisch" share the stem, so a pattern on the stem would give a German sentence
        # the English reply.
        r"anaphylaxis|anaphylactic\w*",
        r"(?:throat|tongue|lips?) (?:is |are )?swell\w*",
        r"allergic reaction.{0,30}breath",
        _de(r"anaphylaxie|anaphylakt\w*"),
        _de(r"allergisch\w*\s+schock\w*"),
        _de(
            r"(?:zunge|lippen?)\s+(?:\w+\s+)?"
            r"(?:schwillt|schwellen|ist geschwollen|sind geschwollen)"
        ),
    ],
    "overdose_poisoning": [
        r"overdos\w*",
        r"poison\w*",
        r"swallowed (?:bleach|pills)",
        _de(r"überdosi\w*"),
        _de(r"\w*vergift\w*"),  # also compounds: Alkoholvergiftung, Lebensmittelvergiftung
    ],
    "seizure": [
        r"seizure",
        r"convuls\w*",
        _de(r"krampfanf(?:a|ä)ll\w*"),  # Krampfanfall, Krampfanfälle
        _de(r"epileptisch\w*\s+anfall\w*"),  # epileptischer / epileptischen Anfall
        _de(r"fieberkr(?:a|ä)mpf\w*"),
    ],
}

_COMPILED: dict[str, dict[str, re.Pattern[str]]] = {
    category: {
        language: re.compile(
            r"\b(?:" + "|".join(p for p in patterns if _language_of(p) == language) + r")",
            re.IGNORECASE,
        )
        for language in ("en", "de")
        if any(_language_of(p) == language for p in patterns)
    }
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

# English texts live in texts.py (with the German ones); re-exported so imports keep working.
EMERGENCY_MESSAGE = EN.emergency_message
SAFETY_NOTICE = EN.safety_notice

POISONING_CATEGORY = "overdose_poisoning"  # its reply also lists the poison information centres


def emergency_reply(language: str, category: str | None = None) -> str:
    """The fixed emergency reply in `language`; the poisoning category gets the poison line."""
    texts = texts_for(language)
    if category == POISONING_CATEGORY:
        return texts.emergency_poisoning_message
    return texts.emergency_message


def _normalise(text: str) -> str:
    # NFC so composed and decomposed umlauts match the same pattern; collapse whitespace.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _is_informational(text: str) -> bool:
    return bool(_QUESTION_START.search(text)) and not _PERSON.search(text)


def detect_red_flag(text: str) -> RedFlag | None:
    """Return the first red flag found in the user's message (by category order), or None.

    All patterns are checked so the language can be decided: German only if nothing English
    matched too (a German sentence with an English loanword such as "stroke" gets the English
    reply, which is the safe default)."""
    normalised = _normalise(text)
    first: tuple[str, str] | None = None
    languages: set[str] = set()
    for category, by_language in _COMPILED.items():
        for language, pattern in by_language.items():
            match = pattern.search(normalised)
            if match:
                languages.add(language)
                if first is None:
                    first = (category, match.group(0))
    if first is None:
        return None
    return RedFlag(
        first[0],
        first[1],
        informational=_is_informational(normalised),
        language="de" if languages == {"de"} else "en",
    )
