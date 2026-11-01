"""One call that applies every deterministic, LLM-free safety rule to an incoming message.

Used by the guardrail node (first step of every turn) and by the API's limit path, so a message
that needs a safety answer gets it even when a daily limit or budget has been reached.

Order matters: harmful intent first. Its reply gives no information and lists crisis resources,
which also covers messages that combine a method question with suicidal intent.
"""

from dataclasses import dataclass
from typing import Literal

from medagent.guardrails.emergency import detect_red_flag, emergency_reply
from medagent.guardrails.harmful import detect_harmful_intent
from medagent.guardrails.self_harm import detect_self_harm_support
from medagent.guardrails.texts import texts_for


@dataclass(frozen=True, slots=True)
class Screen:
    kind: Literal["harmful_intent", "emergency", "self_harm_support"]
    category: str  # e.g. "lethal_dose" or "cardiac": safe to log, never the user's text
    reply: str  # the fixed answer to send, with no LLM call, in the language of the matched rule
    language: str = "en"


def screen_message(text: str) -> Screen | None:
    """A fixed safety reply if the message needs one, else None.

    General questions about emergencies ("what are the signs of a stroke?") return None here:
    they are answered normally, with a safety notice (see the guardrail node).
    """
    harmful = detect_harmful_intent(text)
    if harmful is not None:
        return Screen(
            "harmful_intent",
            harmful.kind,
            texts_for(harmful.language).harmful_message,
            harmful.language,
        )
    flag = detect_red_flag(text)
    if flag is not None and not flag.informational:
        return Screen(
            "emergency", flag.category, emergency_reply(flag.language, flag.category), flag.language
        )
    support = detect_self_harm_support(text)
    if support is not None:
        return Screen(
            "self_harm_support",
            support.category,
            texts_for(support.language).self_harm_message,
            support.language,
        )
    return None
