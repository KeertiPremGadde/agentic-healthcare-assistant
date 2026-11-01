"""Fixed reply texts, English and German.

These are the sentences the assistant says itself (never model output): the "I don't know"
reply, the dose referral, the disclaimer and the labels of the sources block, and the safety
replies (emergency, harmful intent, the notice in front of a general emergency question).
The reply language is decided once per turn from the router's `language` (`reply_language`).
Only German has its own set; any other language falls back to English rather than guessing a
translation.

The output guard accepts the texts of *every* language (a reply is checked against all of them),
and appends the one for the turn's language when something is missing. The frontend parses the
same labels (`frontend/src/lib/citations.ts`): change them in both places.

The safety replies are chosen where the language is known: by the rule that matched (the rules
run before any model call), or by the router's language when only its flags caught the message.

No imports on purpose: `disclaimer.py`, `dose.py`, `emergency.py`, `harmful.py` and `rag/answer.py`
re-export the English strings from here, so everything that already imports them keeps working
unchanged.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedTexts:
    language: str
    no_answer: str  # no reliable evidence: said without calling the model
    dose_referral: str  # a dose or quantity of a medicine was about to be shown
    disclaimer: str
    sources_label: str  # the line that opens the sources list ("Sources:")
    content_label: str  # prefix of the attribution lines ("Content: ...")
    emergency_message: str  # someone may be in acute danger: fixed reply, no model call
    emergency_poisoning_message: str  # the same, for a suspected poisoning or overdose
    harmful_message: str  # harmful intent (lethal dose, harming someone, suicide method)
    self_harm_message: str  # self-harm or passive ideation, not acute: support, no refusal
    safety_notice: str  # in front of an answer to a general question about an emergency


# Poison information centres (Giftinformationszentren), emergency ("Notruf") numbers from the
# official BfR directory: https://www.bfr.bund.de/deutsches-produktregister-de-pro/
# giftinformationszentren-in-deutschland/ (Stand 22.07.2026). The directory states no opening
# hours, so none are claimed here. Re-check when the directory is updated.
POISON_CENTRES_DE: tuple[tuple[str, str], ...] = (
    ("Berlin", "030 19240"),
    ("Bonn", "0228 19240"),
    ("Erfurt", "0361 730730"),
    ("Freiburg", "0761 19240"),
    ("Göttingen", "0551 19240"),
    ("Mainz", "06131 19240"),
    ("München", "089 19240"),
)
_POISON_LINE_DE = (
    "Bei schweren Symptomen wie Bewusstlosigkeit, Atemnot oder Krampfanfällen wählen Sie sofort "
    "die 112. Bei Verdacht auf eine Vergiftung erreichen Sie ein Giftinformationszentrum "
    "(Giftnotruf): " + " · ".join(f"{city} {number}" for city, number in POISON_CENTRES_DE) + "."
)

_EMERGENCY_EN = (
    "This may be a medical emergency. Please call emergency services now: 112 in Germany and the "
    "EU (Notruf 112), 911 in the US. If someone is unconscious or not breathing, call immediately "
    "and follow the dispatcher's instructions. For thoughts of suicide or self-harm in Germany you "
    "can also call the TelefonSeelsorge on 0800 111 0 111 (free, 24/7).\n\n"
    "I can't assess emergencies. If this is not acute, tell me and I can help you find a doctor "
    "or book an appointment."
)
_HARMFUL_EN = (
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
# Not acute and not a request for information: someone says they hurt themselves, or that life is
# too much. Short, warm, no refusal, no "I can't help". The numbers are from the official pages
# (checked 2026-11-01): telefonseelsorge.de (0800 111 0 111, 0800 111 0 222, 116 123: free,
# anonymous, day and night), nummergegenkummer.de (116 111 Kinder- und Jugendtelefon, Mon-Sat
# 14-20 Uhr, free, anonymous; Elterntelefon 0800 111 0550), 116117.de (Terminservice for doctors
# and psychotherapists for the statutory insured; the line is open day and night). 112 only for
# danger right now. 988 for the US, as in the other safety replies.
_SELF_HARM_EN = (
    "Thank you for telling me. What you describe sounds painful, and you don't have to go through "
    "it alone. There is help, and it is okay to ask for it.\n\n"
    "You can talk to someone at any time:\n"
    "- Germany: TelefonSeelsorge, free and anonymous, day and night: 0800 111 0 111 or 116 123\n"
    "- US: call or text 988\n"
    "- Worried about a child or teenager? Nummer gegen Kummer in Germany: 116 111 for children "
    "and teenagers (free, anonymous, Mon-Sat 2-8 pm), 0800 111 0550 for parents\n\n"
    "If you are in danger right now, call 112.\n\n"
    "I can also help you find a doctor or a therapist, or book an appointment. In Germany, "
    "116 117 can arrange an appointment with a psychotherapist if you have statutory health "
    "insurance."
)
_SAFETY_NOTICE_EN = (
    "If you or someone near you has these symptoms right now, call emergency services "
    "(112 in Germany/EU, 911 in the US)."
)

_SELF_HARM_DE = (
    "Danke, dass Sie mir das erzählen. Was Sie beschreiben, klingt schmerzhaft, und Sie müssen "
    "damit nicht allein bleiben. Es gibt Hilfe, und es ist in Ordnung, sie anzunehmen.\n\n"
    "Sie können jederzeit mit jemandem sprechen:\n"
    "- TelefonSeelsorge, kostenlos, anonym, Tag und Nacht: 0800 111 0 111 oder 116 123\n"
    "- Sorge um ein Kind oder eine Jugendliche oder einen Jugendlichen? Nummer gegen Kummer: "
    "116 111 für Kinder und Jugendliche (kostenlos, anonym, Mo-Sa 14-20 Uhr), "
    "0800 111 0550 für Eltern\n\n"
    "Wenn Sie sich jetzt in Gefahr befinden, rufen Sie die 112 an.\n\n"
    "Ich kann Ihnen auch helfen, eine Ärztin, einen Arzt oder einen Therapieplatz zu finden "
    "oder einen Termin zu buchen. Einen Termin bei einer Psychotherapeutin oder einem "
    "Psychotherapeuten vermittelt auch die Terminservicestelle unter 116 117 (für gesetzlich "
    "Versicherte)."
)

_EMERGENCY_DE_FIRST = (
    "Das könnte ein medizinischer Notfall sein. Bitte rufen Sie jetzt den Notruf an: 112. Wenn "
    "jemand bewusstlos ist oder nicht atmet, rufen Sie sofort an und folgen Sie den Anweisungen "
    "der Leitstelle. Bei Gedanken an Suizid oder Selbstverletzung erreichen Sie die "
    "TelefonSeelsorge kostenlos, anonym und rund um die Uhr unter 0800 111 0 111."
)
_EMERGENCY_DE_LAST = (
    "Ich kann Notfälle nicht einschätzen. Wenn es nicht akut ist, sagen Sie es mir, dann helfe "
    "ich Ihnen, eine Ärztin oder einen Arzt zu finden oder einen Termin zu buchen. Außerhalb der "
    "Sprechzeiten erreichen Sie den ärztlichen Bereitschaftsdienst unter 116 117."
)
_HARMFUL_DE = (
    "Es tut mir leid, dabei kann ich nicht helfen, und ich darf dazu auch keine Informationen "
    "geben.\n\n"
    "Wenn Sie daran denken, sich das Leben zu nehmen oder sich zu verletzen, müssen Sie das nicht "
    "allein tragen. Bitte melden Sie sich jetzt: TelefonSeelsorge, kostenlos, anonym und rund um "
    "die Uhr: 0800 111 0 111 (oder 116 123). In einer akuten Gefahr: 112.\n\n"
    "Wenn Sie befürchten, jemand anderem zu schaden, rufen Sie bitte die 112 an oder sprechen Sie "
    "heute noch mit einer Ärztin, einem Arzt oder einer Vertrauensperson.\n\n"
    "Hat jemand versehentlich etwas Gefährliches verschluckt? " + _POISON_LINE_DE + "\n\n"
    "Bei anderen Gesundheitsfragen, bei der Suche nach einer Ärztin oder einem Arzt oder bei "
    "einer Terminbuchung helfe ich gern."
)

EN = FixedTexts(
    language="en",
    no_answer=(
        "I don't know: the knowledge base doesn't contain enough relevant information to answer "
        "that reliably. Please ask a healthcare professional."
    ),
    dose_referral=(
        "I can't give specific doses or amounts of medicines. The right amount depends on your "
        "age, weight, health and other medicines you take, so please ask your doctor or "
        "pharmacist, and follow the instructions in the package leaflet. I'm happy to explain how "
        "a medicine works or what its side effects are."
    ),
    disclaimer=(
        "This is general health information from the sources listed above, not medical advice or "
        "a diagnosis. Please consult a qualified healthcare professional. In an emergency, call "
        "your local emergency number (112 in the EU, 911 in the US)."
    ),
    sources_label="Sources:",
    content_label="Content:",
    emergency_message=_EMERGENCY_EN,
    emergency_poisoning_message=_EMERGENCY_EN,  # English is unchanged: no separate poison line
    harmful_message=_HARMFUL_EN,
    self_harm_message=_SELF_HARM_EN,
    safety_notice=_SAFETY_NOTICE_EN,
)

DE = FixedTexts(
    language="de",
    no_answer=(
        "Dazu kann ich leider keine verlässliche Antwort geben: Meine Wissensbasis enthält nicht "
        "genug passende Informationen. Bitte wenden Sie sich an Ihre Ärztin, Ihren Arzt oder Ihre "
        "Apotheke."
    ),
    dose_referral=(
        "Ich kann keine konkreten Dosierungen oder Mengen von Medikamenten nennen. Die richtige "
        "Menge hängt von Alter, Gewicht, Gesundheitszustand und weiteren Medikamenten ab. Bitte "
        "fragen Sie Ihre Ärztin, Ihren Arzt oder Ihre Apotheke und beachten Sie den "
        "Beipackzettel. Gerne erkläre ich, wie ein Medikament wirkt oder welche Nebenwirkungen es "
        "hat."
    ),
    disclaimer=(
        "Dies sind allgemeine Gesundheitsinformationen aus den oben genannten Quellen, keine "
        "medizinische Beratung und keine Diagnose. Bitte wenden Sie sich an Ihre Ärztin oder "
        "Ihren Arzt. Außerhalb der Sprechzeiten erreichen Sie den ärztlichen Bereitschaftsdienst "
        "unter 116 117. Im Notfall wählen Sie 112."
    ),
    sources_label="Quellen:",
    content_label="Inhalt:",
    emergency_message=_EMERGENCY_DE_FIRST + "\n\n" + _EMERGENCY_DE_LAST,
    emergency_poisoning_message=(
        _EMERGENCY_DE_FIRST + "\n\n" + _POISON_LINE_DE + "\n\n" + _EMERGENCY_DE_LAST
    ),
    harmful_message=_HARMFUL_DE,
    self_harm_message=_SELF_HARM_DE,
    safety_notice=(
        "Wenn Sie oder jemand in Ihrer Nähe diese Symptome gerade haben, wählen Sie den Notruf 112."
    ),
)

ALL_TEXTS = (EN, DE)

# When the router fails the message has not been checked for danger and its language is unknown
# (the rules had no match to tell): a neutral request to rephrase, then the emergency and crisis
# lines in both languages. Not a refusal: the user is most likely benign and the cause an outage.
ROUTER_FAILURE_MESSAGE = (
    "I couldn't process that message just now. Please try again, or rephrase it.\n\n"
    "If this is an emergency, call 112 (911 in the US). If you are thinking about hurting "
    "yourself, you can reach the TelefonSeelsorge in Germany any time on 0800 111 0 111 (free, "
    "anonymous), or call or text 988 in the US.\n\n"
    "Ich konnte Ihre Nachricht gerade nicht verarbeiten. Bitte versuchen Sie es noch einmal oder "
    "formulieren Sie sie anders.\n\n"
    "Im Notfall wählen Sie die 112. Wenn Sie daran denken, sich etwas anzutun, erreichen Sie die "
    "TelefonSeelsorge jederzeit kostenlos und anonym unter 0800 111 0 111."
)


def reply_language(code: str | None) -> str:
    """The language of the fixed texts for an ISO 639-1 code: "de" for German, else "en"."""
    return "de" if (code or "").strip().lower().split("-")[0] == "de" else "en"


def texts_for(language: str | None) -> FixedTexts:
    return DE if reply_language(language) == "de" else EN
