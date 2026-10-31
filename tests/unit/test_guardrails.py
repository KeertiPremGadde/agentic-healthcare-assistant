import pytest

from medagent.guardrails.emergency import detect_red_flag
from medagent.guardrails.pii import mask_pii, pseudonymise


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I have crushing chest pain and my left arm hurts", "cardiac"),
        ("my dad says he can't breathe", "breathing"),
        ("I think I'm having a heart attack", "cardiac"),
        ("her face is drooping and she has slurred speech", "stroke"),
        ("I want to kill myself", "self_harm"),
        ("my friend passed out and is unresponsive", "unconscious"),
        ("I'm bleeding heavily from a cut", "bleeding"),
        ("my throat is swelling after a bee sting", "anaphylaxis"),
        ("my son swallowed pills from the cabinet", "overdose_poisoning"),
        ("he is having a seizure", "seizure"),
        # German
        ("Ich habe starke Brustschmerzen", "cardiac"),
        ("Mein Vater hat Atemnot", "breathing"),
        ("Ich glaube, meine Mutter hat einen Schlaganfall", "stroke"),
        ("Ich will mir das Leben nehmen", "self_harm"),
        ("Mein Mann ist bewusstlos", "unconscious"),
        ("Ich bekomme keine Luft", "breathing"),
    ],
)
def test_acute_red_flags_short_circuit(text: str, category: str) -> None:
    flag = detect_red_flag(text)
    assert flag is not None
    assert flag.category == category
    assert not flag.informational


def test_decomposed_umlauts_still_match() -> None:
    decomposed = "Ich habe eine Lähmung im Arm"  # "a" + combining diaeresis
    flag = detect_red_flag(decomposed)
    assert flag is not None
    assert flag.category == "stroke"


@pytest.mark.parametrize(
    "text",
    [
        "What are the warning signs of a stroke?",
        "How is a heart attack treated?",
        "What causes shortness of breath at high altitude?",
        "Was sind die Symptome eines Schlaganfalls?",
    ],
)
def test_general_questions_are_informational_not_short_circuited(text: str) -> None:
    flag = detect_red_flag(text)
    assert flag is not None
    assert flag.informational


def test_question_about_a_person_is_still_acute() -> None:
    flag = detect_red_flag("What should I do, I have chest pain?")
    assert flag is not None
    assert not flag.informational


@pytest.mark.parametrize(
    "text",
    [
        "What are the symptoms of diabetes?",
        "Book me a cardiologist next Tuesday afternoon",
        "I have a sore throat and a mild cough",
        "Ich brauche einen Termin beim Hautarzt",
        "Can I see Dr. Wilson on Friday?",
    ],
)
def test_ordinary_messages_have_no_red_flag(text: str) -> None:
    assert detect_red_flag(text) is None


def test_mask_pii() -> None:
    text = (
        "Mail alex@example.com, call +49 30 5550 0101, born 01.02.1990, "
        "IBAN DE89 3704 0044 0532 0130 00"
    )
    masked = mask_pii(text)
    assert "alex@example.com" not in masked
    assert "5550" not in masked
    assert "1990" not in masked
    assert "DE89" not in masked
    assert "[email]" in masked
    assert "[phone]" in masked


def test_pseudonymise_is_stable_and_not_reversible() -> None:
    assert pseudonymise(42) == pseudonymise(42)
    assert pseudonymise(42) != pseudonymise(43)
    assert "42" not in pseudonymise(42)
