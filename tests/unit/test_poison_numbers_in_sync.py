"""The poison-centre numbers exist twice: in the German fixed replies (texts.py) and in the
frontend (the crisis card and the tappable-number list). They are the same seven BfR lines
(Stand 22.07.2026); this test fails if one copy is changed without the other."""

import re
from pathlib import Path

from medagent.guardrails.texts import DE, POISON_CENTRES_DE

FRONTEND_LIST = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "poison-centres.ts"
)


def _frontend_centres() -> list[tuple[str, str]]:
    source = FRONTEND_LIST.read_text(encoding="utf-8")
    return re.findall(r'\{ city: "([^"]+)", number: "([^"]+)" \}', source)


def test_the_frontend_lists_exactly_the_centres_of_the_german_replies() -> None:
    assert _frontend_centres() == list(POISON_CENTRES_DE)


def test_every_centre_is_in_the_german_crisis_reply() -> None:
    for city, number in POISON_CENTRES_DE:
        assert f"{city} {number}" in DE.harmful_message
        assert f"{city} {number}" in DE.emergency_poisoning_message
