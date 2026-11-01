"""Deterministic detection of NON-ACUTE self-harm and passive suicidal ideation (ADR 0021).

The emergency rules cover a statement of acute danger and the explicit words ("ich ritze mich",
"I hurt myself"). This module covers what a person says in their own words when it is not acute:
"I burn myself with cigarettes when I feel bad", "Meine Tochter fügt sich Schnitte am Arm zu",
"Sometimes I think everyone would be better off without me". The red-team baseline (ADR 0020)
found that neither the rules nor the router flagged most of these, so the user got MedlinePlus
text or "I don't know" and no crisis resources.

A hit is answered with the fixed supportive reply (`self_harm_message`): warm, no refusal, the
crisis lines, and 112 only for danger right now. It is not the emergency reply and not the
harmful-intent reply.

How it avoids false alarms ("I burned myself on the stove", "I cut myself shaving", "my cat
scratched me", "my eczema itches until it bleeds"): a plain harm verb is not enough. A pattern of
the VERB kind needs a CUE somewhere in the message that says it is deliberate or a habit: an
emotional trigger ("when it gets too much", "wenn ich Angst habe"), a habit or purpose ("on
purpose", "for years", "um mich zu spüren", "nicht aufhören"), or an instrument made for it
("with a razor", "mit Zigaretten"). The EXPLICIT patterns ("makes himself bleed", "fügt sich
Schnitte zu", "better off without me") need no cue.

General questions ("Why do teenagers hurt themselves when they are stressed?") are not matched:
they are answered with a safety notice, like the other red-flag questions.
"""

import re
from dataclasses import dataclass

from medagent.guardrails.emergency import _is_informational, _normalise


class _German(str):
    """A pattern that matches German phrasing: it decides the language of the reply, as in the
    other rule modules."""


_de = _German


@dataclass(frozen=True, slots=True)
class SelfHarmFlag:
    category: str  # "self_injury" | "passive_ideation" (safe to log, never the text)
    language: str = "en"


# ---- English building blocks ----------------------------------------------------------------
_REFL = r"(?:myself|himself|herself|themselves?)(?!\s+(?:some slack|off|out|up|down|in)\b)"
_BODY = r"(?:arms?|forearms?|thighs?|wrists?|legs?|skin|body|stomach|chest)"  # not hands: cooking
_HARM = (
    r"(?:burn\w*|cut\w*|scratch\w*|hit\w*|punch\w*|slap\w*|slash\w*|pick\w*|hurt\w*|harm\w*"
    r"|injur\w*|mutilat\w*|stab\w*|carv\w*|bang\w*)"
)
_EN_VERB = (
    rf"(?:\b{_HARM}\s+{_REFL}\b"  # "burn myself", "keeps hurting himself"
    rf"|\b{_HARM}\s+(?:at\s+)?(?:my|his|her|their)\s+{_BODY}\b"  # "I cut my thighs"
    r"|\b(?:bang\w*|hit\w*|slam\w*|beat\w*)\s+(?:my|his|her|their)\s+head\s+against\b)"
)
_EN_CUE = (
    r"(?:\b(?:too much|overwhelm\w*|can'?t cope|cannot cope|stress\w*|anxi\w*|upset|angry"
    r"|depress\w*|panic\w*|pressure|lonely|numb|empty|worthless|ashamed|hate myself"
    r"|feel(?:s|ing)? (?:bad|awful|terrible|low))\b"  # an emotional trigger
    r"|\b(?:on purpose|deliberately|intentionally|can'?t stop|cannot stop|keeps?|kept"
    r"|for (?:years|months|weeks)|every (?:day|night|time)|to (?:feel|cope|punish|relieve"
    r"|release|numb))\b"  # a habit or a purpose
    r"|\bwith (?:a |the |my )?(?:razor|blade|knife|lighter|cigarettes?|scissors|glass|compass)\b)"
)
# A hurt that is plainly an accident or a sport, however it is said: not deliberate.
_EN_ACCIDENT = re.compile(
    r"\b(?:itch\w*|eczema|rash|allerg\w*|mosquito|playing|plays?|while|during|falling|fell|climbing|lifting|cooking|shaving|baking"
    r"|gardening|garden|chopping|slicing|peeling|carving a|opening|kitchen|workshop|gym|training"
    r"|workout|sports?|bike|bicycle|skateboard|slipped|tripped|dropped|sawing|accident\w*"
    r"|by accident|on the (?:stove|oven|iron|kettle|cooker|hob)"
    r"|on a (?:nail|branch|fence|shelf))\b",
    re.IGNORECASE,
)

# The phrase must END the thought: "better off without me in the meeting" or "I don't see any
# point in going on this diet" are about something else.
_END_INNER = r"\s*(?:[.,!?;]|$|and\b|because\b|but\b|so\b)"
_END = rf"(?={_END_INNER})"
_PASSIVE_EN = [
    rf"\b(?:better off|easier|simpler|happier)\b.{{0,40}}\bwithout me{_END}",
    r"\b(?:better|easier|simpler)\b.{0,50}\bif i (?:(?:wasn'?t|weren'?t) (?:here|around|alive"
    r"|born|there)|didn'?t exist|disappeared|were gone|was gone)\b",
    rf"\b(?:no|don'?t see (?:any|a)|can'?t see (?:any|a)) point (?:in )?(?:(?:going on|continuing"
    rf"|carrying on|living){_END}|anymore|any more)\b",
    r"\ba burden (?:to|on) (?:everyone|everybody|all|others|everyone around me"
    r"|my (?:family|friends|parents|kids|children|loved ones))\b",
    rf"\b(?:can'?t|cannot) (?:take|bear|stand|do) (?:this|my) (?:life|existence)"
    rf"(?=\s*(?:anymore|any more|much longer)|{_END_INNER})",
    r"\bdisappear\w* (?:for good|forever)\b",
]
_EXPLICIT_EN = [
    rf"\bmak(?:e|es|ing|made) {_REFL} bleed\b",
    r"\bself[- ]?injur\w*",
    rf"\bpunish\w* {_REFL} (?:by|with)\s+(?:cutting|burning|hitting|hurting|making)\b",
    # "she does it to herself" after talk of cuts or scars
    rf"\b(?:cuts?|scars?|burns?|wounds?)\b.{{0,60}}\b(?:does|do|did) it to {_REFL}\b",
    r"\b(?:hid\w*|cover\w*)\s+(?:up\s+)?(?:the |my |her |his )?(?:scars|cuts|marks|burns)\b"
    r".{0,40}\b(?:arms?|legs?|thighs?|wrists?)\b",
    r"\brelaps\w*\b.{0,60}\b(?:cut|scratch|burn|hurt|bleed|harm)\w*",
]

# ---- German building blocks -----------------------------------------------------------------
_DE_REFL = r"(?:mich|mir|sich)"
# First-person forms ("verletze", not "verletzt"): "das verletzt mich" is also "that hurts my
# feelings" and "der Wind schneidet mir ins Gesicht". "sich" is always reflexive.
_DE_HARM_1P = r"(?:verbrenne|kratze|schneide|verletze|ritze)(?!\w)"
_DE_HARM_INF = r"(?:verbrennen|kratzen|schneiden|verletzen)(?!\s+lassen)\b"
_DE_VERB = (
    rf"(?:\b{_DE_HARM_1P}\s+(?:\w+\s+){{0,2}}(?:mich|mir)\b"  # "verbrenne mich", "schneide ich mir"
    rf"|\b(?:mich|mir)\s+(?:\w+\s+){{0,3}}{_DE_HARM_INF}"  # "um mich zu verletzen"
    r"|\b(?:verbrenn|kratz|schneid|verletz)\w*\s+(?:\w+\s+){0,2}sich\b"  # "verbrennt sich"
    r"|\b(?:tu|tue|tust|tut|tun)\s+(?:mir|mich|sich)\s+(?:selbst\s+)?weh\b"
    r"|\b(?:wehzutun|weh\s+zu\s+tun)\b"
    r"|\bschlag\w*\s+(?:\w+\s+){0,3}kopf\s+gegen\s+(?:die|eine)\s+wand\b)"
)
_DE_CUE = (
    r"(?:\b(?:zu viel|überfordert|angst|druck|stress\w*|schlecht|traurig|wütend|panik\w*"
    r"|einsam|leer|taub|wertlos|nicht mehr aushalte\w*|spüren)\b"
    r"|\b(?:absichtlich|mit absicht|nicht aufhören|immer wieder|jede[nr]?\s+(?:tag|nacht)"
    r"|seit\s+(?:jahren|monaten|wochen)|um\s+(?:\w+\s+){0,3}zu)\b"
    r"|\bmit\s+(?:einer?|dem|der|den)?\s*(?:rasierklinge|klinge|messer|feuerzeug|zigarette\w*"
    r"|schere|glasscherbe\w*)\b)"
)
_DE_ACCIDENT = re.compile(
    r"\b(?:juck\w*|ausschlag|ekzem|neurodermitis|allergi\w*|mücke|beim|beim\s+\w+|spielen|sport|gefallen|gestürzt|herd|bügeleisen|kochen|rasieren"
    r"|fußball|fahrrad\w*|radfahren)\b",
    re.IGNORECASE,
)
_PASSIVE_DE = [
    r"\bohne mich\b.{0,30}\b(?:besser dran|besser|leichter)\b",
    r"\b(?:besser|leichter)\b.{0,40}\b(?:wenn es mich nicht (?:mehr )?gäbe"
    r"|wenn ich nicht (?:mehr )?(?:da|hier) wäre|ohne mich)\b",
    r"\bkeinen sinn mehr\b.{0,30}\b(?:weiterzumachen|weiterzuleben|zu leben|weiter\b)",
    r"\b(?:eine|ne) last für (?:alle|andere|jeden|meine (?:familie|eltern|freunde|kinder))\b",
    r"\b(?:halte|ertrage|schaffe)\b.{0,12}\b(?:dieses|mein) leben nicht mehr\b",
    r"\bfür immer verschwinden\b",
]
_EXPLICIT_DE = [
    # "fügt sich Schnitte am Arm zu", "dass sich meine Schwester selbst Schmerzen zufügt"
    rf"\b{_DE_REFL}\s+(?:selbst\s+)?(?:\w+\s+){{0,3}}(?:schmerzen|schnitte|wunden|verletzungen)"
    r"\s+(?:\w+\s+){0,3}?(?:zu\b|zufüg\w*)",
    r"\b(?:schmerzen|schnitte|wunden|verletzungen)\s+(?:selbst\s+)?zufüg\w*",
    # "er tut sich selbst weh", "ich tue mir selbst weh" (not "das tut mir selbst weh")
    r"\b(?:tut|tun)\s+sich\s+selbst\s+weh\b|\btue\s+mir\s+selbst\s+weh\b",
    r"\b(?:mich|sich)\s+(?:\w+\s+){0,3}geritzt",
    r"\britz\w*\s+(?:\w+\s+){0,2}(?:mich|sich)\b",
]


def _compile(patterns: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


_RULES = {
    "en": {
        "verb": re.compile(_EN_VERB, re.IGNORECASE),
        "cue": re.compile(_EN_CUE, re.IGNORECASE),
        "accident": _EN_ACCIDENT,
        "explicit": _compile(_EXPLICIT_EN),
        "passive": _compile(_PASSIVE_EN),
    },
    "de": {
        "verb": re.compile(_DE_VERB, re.IGNORECASE),
        "cue": re.compile(_DE_CUE, re.IGNORECASE),
        "accident": _DE_ACCIDENT,
        "explicit": _compile(_EXPLICIT_DE),
        "passive": _compile(_PASSIVE_DE),
    },
}


# A question about people in general ("Why do teenagers hurt themselves when they are stressed?")
# has no "I" / "my" in it: it is answered with a notice. The shared informational check counts
# "they" as a person, which is right for a stroke ("he is slurring") but not for this.
_QUESTION = re.compile(
    r"^(?:what|how|why|which|when|who|warum|wieso|weshalb|wie|was|wann|wer)\b", re.I
)
_FIRST_PERSON = re.compile(
    r"\b(?:i|i'm|i've|me|my|mine|we|our|us|ich|mir|mich|mein\w*|wir|uns|unser\w*)\b", re.I
)


def _general_question(text: str) -> bool:
    return bool(_QUESTION.search(text)) and not _FIRST_PERSON.search(text)


def _match(text: str, language: str) -> str | None:
    rules = _RULES[language]
    if rules["explicit"].search(text):
        return "self_injury"
    if rules["passive"].search(text):
        return "passive_ideation"
    verb, cue = rules["verb"].search(text), rules["cue"].search(text)
    if verb and cue and not rules["accident"].search(text):
        return "self_injury"
    return None


def detect_self_harm_support(text: str) -> SelfHarmFlag | None:
    """A flag if the message says, in the first person or about someone close, that they hurt
    themselves or that life is too much, and it is not a general question."""
    normalised = _normalise(text)
    if _is_informational(normalised) or _general_question(normalised):
        return None
    found = {lang: _match(normalised, lang) for lang in ("en", "de")}
    hits = {lang: cat for lang, cat in found.items() if cat}
    if not hits:
        return None
    # German only if nothing English matched too: the safe default is the English reply.
    language = "de" if set(hits) == {"de"} else "en"
    return SelfHarmFlag(hits[language] if language in hits else next(iter(hits.values())), language)
