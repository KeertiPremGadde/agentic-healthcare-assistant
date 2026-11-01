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
        r"cardiac arrest|heart (?:has |had )?stopped",
        r"(?:pressure|tightness|heaviness) (?:in|on) (?:\w+ ){0,2}chest\b",
        r"chest (?:pressure|tightness)",
        _de(r"herzstillstand"),
        _de(r"(?:druck|enge) (?:auf|in) (?:\w+ ){0,2}brust\b|brustenge\w*"),
        _de(r"(?:schmerzen|druck|enge|engegefühl) im brustkorb\b"),
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
        r"gasping for (?:air|breath)|can'?t catch (?:my|his|her|their) breath",
        _de(r"(?:ring\w*|japs\w*) nach luft"),
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
        r"slurr(?:ing|ed) (?:(?:his|her|my|their|the) )?(?:words|speech)",
        r"(?:sudden(?:ly)?|one side).{0,30}(?:numb|weak|paraly[sz]ed)",
        r"sudden(?:ly)?.{0,30}can'?t (?:lift|raise|move)",
        # "lallt" alone is also a baby babbling: only together with another stroke sign
        _de(r"lall\w*\b.{0,40}\b(?:arm|bein|gesicht|mundwinkel|gelähmt|heben)"),
        _de(r"plötzlich.{0,40}\b(?:arm|bein)\b.{0,20}nicht (?:mehr )?(?:heben|bewegen)"),
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
        # not "I don't want to live in Berlin anymore" / "...to go on a diet"
        r"(?:don'?t|do not|no longer) want to (?:live|be alive|go on)\b"
        r"(?!\s+(?:in|at|with|near|here|there|alone|by|on|abroad|together|a|an|the|my|this|that"
        r"|holiday|vacation)\b)",
        r"better off dead",
        r"(?:wish|wished) i (?:was|were) dead",
        # not an accident: "I hurt myself playing football", but a bare "I hurt myself" still counts
        # (ambiguous: the emergency reply). "I've been hurting myself" is habitual: "self_injury".
        r"(?<!been )(?<!keep )(?<!keeps )(?<!kept )(?<!started )(?<!always )(?<!often )(?<!stop )"
        r"hurt(?:ing)? myself(?!\s+(?:playing|while|during|at\b|in the|on the|doing|lifting"
        r"|running|training|today|yesterday|last\b|badly|a little|a bit|slightly|falling"
        r"|cooking|skiing|cycling|biking|jogging|exercising|shaving))",
        r"(?:want|going|ready|need|plan(?:ning)?) to end it\b"
        r"(?!\s+(?:with|for|between|after|before|by|when|if)\b)",
        r"(?:don'?t|do not) want to be (?:here|around|alive) (?:any ?more|any longer)",
        r"(?:no|not any) (?:point|reason|sense) (?:in|to) (?:living|live|going on|life)",
        r"life (?:is not|isn'?t|is no longer) worth living",
        _de(r"suizid\w*"),
        _de(
            r"(?:will|m(?:ö|oe)chte|m(?:ö|oe)chten|wollte|w(?:ü|ue)rde gerne?) "
            r"(?:(?!nicht\b)\w+ ){0,2}(?:sterben|tot sein)\b"
        ),
        _de(r"nicht mehr da sein\b(?!\s+f(?:ü|ue)r\b)"),
        _de(r"keine lust mehr (?:zu leben|auf das leben|weiterzuleben)"),
        _de(r"lebensm(?:ü|ue)de\w*"),
        _de(r"nicht (?:mehr )?weiterleben"),
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
        r"collaps(?:ed|ing)\b(?! lung)",
        # a person, not a website: "he isn't responding", but not "the portal isn't responding"
        r"(?:he|she|they|baby|child|toddler|patient|person|dad|mum|mom|husband|wife|son|daughter)"
        r" (?:is not|isn'?t|won'?t|doesn'?t|not) (?:responding|respond|reacting|react)",
        _de(
            r"(?:er|sie|vater|mutter|mann|frau|kind|baby|opa|oma|patient\w*|jemand) "
            r"(?:\w+ ){0,2}(?:zusammengebrochen|zusammengesackt|kollabiert)"
        ),
        # "reagiert nicht" next to a person, not "reagiert nicht auf das Medikament"
        _de(
            r"(?:er|sie|kind|baby|opa|oma|vater|mutter|jemand)\b.{0,40}\breagiert "
            r"(?:nicht|nicht mehr|gar nicht)\b(?!\s+auf\s+(?!ansprache|anrufe|rufen|schmerz))"
        ),
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
        r"bleeding (?:heavily|a lot|badly|profusely|won'?t stop)",
        r"vomiting blood|(?:coughing|throwing|spitting) up blood|spitting blood",
        _de(r"starke blutung\w*"),
        _de(r"(?:heftige|massive|schwere)[rsmn]? blutung\w*"),
        _de(
            r"blutung\w* (?:\w+ ){0,2}"
            r"(?:hört nicht auf|steht nicht|nicht zu stoppen|lässt sich nicht stoppen)"
        ),
        _de(r"(?:spuckt|hustet) blut\b"),
        _de(r"blutet (?:\w+ )?(?:heftig|massiv|wie verrückt)"),
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
        r"throat (?:is |are )?(?:closing|swelling shut|tightening)",
        _de(r"hals (?:\w+ )?(?:schwillt zu|schnürt sich zu|ist zugeschwollen|wird zu)"),
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
        r"(?:swallowed|took|taken|drank|ingested|ate|eaten) (?:\w+ ){0,3}?"
        r"(?:bleach|detergent|antifreeze|cleaning (?:fluid|products?|liquid)"
        r"|too many (?:pills|tablets|painkillers|meds|medication)"
        r"|a lot of (?:pills|tablets|painkillers))",
        _de(
            r"zu viele (?:tabletten|pillen|medikamente|schlaftabletten) (?:\w+ )?"
            r"(?:geschluckt|genommen|eingenommen)"
        ),
        _de(
            r"(?:reiniger|putzmittel|waschmittel|bleiche|frostschutz\w*|sp(?:ü|ue)lmittel|rohrfrei\w*)"
            r" (?:\w+ )?(?:getrunken|geschluckt|verschluckt)"
        ),
        _de(r"gift (?:getrunken|geschluckt|verschluckt|genommen)"),
        _de(r"überdosi\w*"),
        _de(r"\w*vergift\w*"),  # also compounds: Alkoholvergiftung, Lebensmittelvergiftung
    ],
    "seizure": [
        r"seizure",
        r"convuls\w*",
        r"shaking (?:all over|uncontrollably)|having a fit",
        _de(r"zuck\w* (?:\w+ )?am ganzen (?:körper|leib)"),
        _de(r"krampfanf(?:a|ä)ll\w*"),  # Krampfanfall, Krampfanfälle
        _de(r"epileptisch\w*\s+anfall\w*"),  # epileptischer / epileptischen Anfall
        _de(r"fieberkr(?:a|ä)mpf\w*"),
    ],
    # Habitual or deliberate self-injury, said as a fact about a life: the supportive reply, not
    # the emergency reply (ADR 0021, follow-up). LAST in this dict on purpose: the first category
    # found decides, so when another one also matches ("I cut myself on purpose and want to die")
    # that one wins. A bare "I hurt myself" is ambiguous and stays in "self_harm".
    "self_injury": [
        r"self[- ]?harm",
        r"(?:harm|harms|harming) (?:myself|himself|herself|themselves?)\b",
        r"hurt(?:s|ing)? (?:himself|herself|themselves?) (?:on purpose|deliberately|intentionally)",
        r"(?:been|keep|keeps|kept|started|always|often|can'?t stop|cannot stop) hurting myself\b",
        r"(?:been|keep|kept|started) cutting (?:myself|himself|herself|themselves?)\b"
        r"(?!\s+(?:some\s+)?slack)",
        r"cut(?:s|ting)? (?:myself|himself|herself|themselves?) "
        r"(?:on purpose|deliberately|intentionally)",
        _de(r"selbstverletz\w*"),
        _de(r"ritz\w* (?:mich|sich)\b|(?:mich|sich) (?:selbst )?(?:ritz\w*|geritzt)"),
        _de(r"verletz\w* (?:mich|sich) selbst|(?:mich|sich) selbst (?:verletz\w*|geschnitten)"),
        _de(r"schneid\w* (?:mich|sich) (?:absichtlich|selbst|mit absicht)"),
        _de(
            r"(?:mir|sich) (?:absichtlich|selbst|mit absicht) "
            r"(?:weh\s?getan|weh\s?tun|wehzutun|schmerzen zugef(?:ü|ue)gt)"
        ),
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
# Politeness in front of a question changes nothing: "Hello! How can I ...", "Hallo, wie ...".
_GREETING_PREFIX = re.compile(
    r"^(?:(?:hi|hello|hey|hallo|moin|guten (?:tag|morgen|abend)|excuse me|entschuldigung"
    r"|please|bitte)[\s,!.:-]*)*",
    re.IGNORECASE,
)
# A general question: starts with a question word, "tell me" or "explain".
_QUESTION_START = re.compile(
    r"^(?:what|how|why|which|when|who|whose|whom|should|could|would|will|did|is|are|can|does|do"
    r"|tell me|explain|define|was|wie|warum|welche\w*|wann|wer|woran|wodurch|wof(?:ü|ue)r"
    r"|weshalb|wieso|ist|sind|erkl(?:ä|ae)r\w*)\b",
    re.IGNORECASE,
)
# A question about KNOWING something (recognise, prevent, understand ...), as opposed to one
# about what to do about something that is happening. Only these let a first-person pronoun
# stay generic: "How can I recognise a stroke?" but not "How do I know if I'm having one?".
_KNOWLEDGE_QUESTION = re.compile(
    r"^(?:(?:how|where|what)\s+(?:can|could|should|do|does|would)\s+(?:i|we|you|one|people)\s+"
    r"(?:recogni[sz]e|identify|spot|detect|prevent|avoid|reduce|lower|lessen|learn|understand"
    r"|diagnose|tell|protect|prepare|find(?:\s+(?:out|information|help))?|read|know\s+about)\b"
    r"|(?:wie|woran|wodurch)\b.{0,60}\b(?:erkenne|erkennt|erkennen|unterscheide|unterscheidet"
    r"|unterscheiden|vorbeug\w*|verhindere|verhindert|verhindern|vermeide|vermeiden|senke|senken"
    r"|reduziere|reduzieren|sch(?:ü|ue)tze|sch(?:ü|ue)tzt|sch(?:ü|ue)tzen)\b(?:\s+(?:ich|man|wir)\b)?"
    r"|wo\s+(?:finde|bekomme)\s+(?:ich\s+)?informationen\b)",
    re.IGNORECASE,
)
# After the knowledge question itself, a NEW subject means a second clause that says what is
# going on, even without punctuation: "how can I recognise a stroke my husband slurs his words",
# "... he cannot move his arm", "wie erkenne ich einen Schlaganfall mein Mann lallt". A pronoun,
# or "my/his/her X" followed by anything that is not a preposition, is such a subject. This is
# structural on purpose: a list of verbs would miss the verb nobody listed.
_NEW_SUBJECT = re.compile(
    r"\b(?:i|he|she|they|we|er|sie|ich|wir)\b"
    r"|\b(?:my|his|her|our|their|mein\w*|sein\w*|ihr\w*|unser\w*)\s+\w+\s+"
    r"(?!(?:from|of|in|for|against|at|before|after|during|with|to|on|by|and|or"
    r"|vor|von|bei|f(?:ü|ue)r|gegen|mit|nach|und|oder|zu)\b)\w",
    re.IGNORECASE,
)
# Signs that it is happening now or to a specific person, even inside a knowledge question.
_HAPPENING_NOW = re.compile(
    r"\b(?:right now|just now|currently|at the moment|this morning|tonight|today"
    r"|gerade|jetzt|eben|soeben|akut)\b",
    re.IGNORECASE,
)
# More than one sentence or a clause joined by a comma: the first words may be a question, the
# rest says what is going on ("How do I know if it is a stroke? My face is drooping").
_MORE_THAN_A_QUESTION = re.compile(r"[,;:]|[.!?]\s*\S")

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
    """Is this a general question (answer it, with a safety notice) rather than a live emergency?

    A question counts as general if it has no person in it, or if it asks to KNOW something
    ("how can I recognise ...", "wie erkenne ich ...") and nothing says it is happening now or to
    someone in particular. When in doubt this stays False: a missed emergency costs more than an
    extra safety notice."""
    body = text[_GREETING_PREFIX.match(text).end() :]  # type: ignore[union-attr]
    if _QUESTION_START.search(body) and not _PERSON.search(body):
        return True
    knowledge = _KNOWLEDGE_QUESTION.search(body)
    return (
        knowledge is not None
        and not _HAPPENING_NOW.search(body)
        and not _MORE_THAN_A_QUESTION.search(body)
        and not _NEW_SUBJECT.search(body[knowledge.end() :])
    )


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
