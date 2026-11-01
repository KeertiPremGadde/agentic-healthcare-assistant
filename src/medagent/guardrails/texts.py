"""Fixed reply texts of the medical-answer path, English and German.

These are the sentences the assistant says itself (never model output): the "I don't know"
reply, the dose referral, the disclaimer and the labels of the sources block. The reply language
is decided once per turn from the router's `language` (`reply_language`). Only German has its own
set; any other language falls back to English rather than guessing a translation.

The output guard accepts the texts of *every* language (a reply is checked against all of them),
and appends the one for the turn's language when something is missing. The frontend parses the
same labels (`frontend/src/lib/citations.ts`): change them in both places.

No imports on purpose: `disclaimer.py`, `dose.py` and `rag/answer.py` re-export the English
strings from here, so everything that already imports them keeps working unchanged.
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
)

ALL_TEXTS = (EN, DE)


def reply_language(code: str | None) -> str:
    """The language of the fixed texts for an ISO 639-1 code: "de" for German, else "en"."""
    return "de" if (code or "").strip().lower().split("-")[0] == "de" else "en"


def texts_for(language: str | None) -> FixedTexts:
    return DE if reply_language(language) == "de" else EN
