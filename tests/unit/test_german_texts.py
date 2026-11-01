"""German fixed texts: refusal, dose referral, labels and disclaimer follow the turn's language.

The properties that matter: English output does not change by a byte; the output guard accepts the
fixed texts of every language and never turns a correct German reply into an English one; the
dose guard knows the German forms German answers use; and none of the fixed texts can trip the
dose guard itself."""

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.nodes.output_guard import output_guard_node
from medagent.agents.runner import run_turn
from medagent.agents.schemas import Route, RouteDecision
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.guardrails.dose import DOSE_REFERRAL, contains_dose
from medagent.guardrails.texts import ALL_TEXTS, DE, EN, reply_language, texts_for
from medagent.rag.answer import NO_ANSWER, AnswerPayload, RagAnswer, SourceRef, answer_question
from medagent.rag.types import Candidate
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM, NoTools

ATTRIBUTION = "MedlinePlus - National Library of Medicine (medlineplus.gov)"
DE_QUESTION = "Was sind die Symptome von Diabetes?"


def _candidate() -> Candidate:
    return Candidate(
        chunk_id=1,
        content="Symptoms of diabetes include thirst and fatigue.",
        document_title="Diabetes",
        source_key="medlineplus",
        url="https://medlineplus.gov/diabetes.html",
        attribution=ATTRIBUTION,
        page=None,
        vector_sim=0.85,
    )


# -- the texts -------------------------------------------------------------------------------


def test_english_texts_are_exactly_what_they_were_before_german_existed() -> None:
    assert DISCLAIMER == (
        "This is general health information from the sources listed above, not medical advice or "
        "a diagnosis. Please consult a qualified healthcare professional. In an emergency, call "
        "your local emergency number (112 in the EU, 911 in the US)."
    )
    assert NO_ANSWER == (
        "I don't know: the knowledge base doesn't contain enough relevant information to answer "
        "that reliably. Please ask a healthcare professional."
    )
    assert DOSE_REFERRAL.startswith("I can't give specific doses or amounts of medicines.")
    assert (EN.sources_label, EN.content_label) == ("Sources:", "Content:")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("de", "de"),
        ("DE", "de"),
        ("de-AT", "de"),
        (" de ", "de"),
        ("en", "en"),
        ("en-US", "en"),
        ("tr", "en"),
        ("fr", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_only_german_gets_its_own_texts_everything_else_falls_back_to_english(
    code: str | None, expected: str
) -> None:
    assert reply_language(code) == expected
    assert texts_for(code).language == expected


def test_german_texts_carry_the_required_wording_and_numbers() -> None:
    assert DE.disclaimer.startswith("Dies sind allgemeine Gesundheitsinformationen")
    assert "116 117" in DE.disclaimer and "112" in DE.disclaimer
    assert DE.no_answer.startswith("Dazu kann ich leider keine verlässliche Antwort geben")
    assert (DE.sources_label, DE.content_label) == ("Quellen:", "Inhalt:")
    for field in ("no_answer", "dose_referral", "disclaimer", "sources_label", "content_label"):
        assert getattr(DE, field) != getattr(EN, field)


@pytest.mark.parametrize("texts", ALL_TEXTS, ids=lambda t: t.language)
def test_no_fixed_text_can_trip_the_dose_guard(texts: object) -> None:
    for field in ("no_answer", "dose_referral", "disclaimer"):
        assert not contains_dose(getattr(texts, field)), field


# -- rendering -------------------------------------------------------------------------------


def _answer(language: str) -> RagAnswer:
    return RagAnswer(
        answer="Symptome sind Durst [MedlinePlus: Diabetes].",
        grounded=True,
        sources=[SourceRef("MedlinePlus: Diabetes", "https://medlineplus.gov/d.html", ATTRIBUTION)],
        language=language,
    )


def test_english_rendering_is_unchanged() -> None:
    assert _answer("en").render() == "\n".join(
        [
            "Symptome sind Durst [MedlinePlus: Diabetes].",
            "",
            "Sources:",
            "- MedlinePlus: Diabetes <https://medlineplus.gov/d.html>",
            "",
            f"Content: {ATTRIBUTION}",
            "",
            DISCLAIMER,
        ]
    )


def test_german_rendering_uses_german_labels_and_disclaimer_but_keeps_citations() -> None:
    reply = _answer("de").render()
    assert "\nQuellen:\n" in reply
    assert f"\nInhalt: {ATTRIBUTION}\n" in reply
    assert reply.endswith(DE.disclaimer)
    assert "[MedlinePlus: Diabetes]" in reply  # the citation label stays English
    assert "Sources:" not in reply and "Content:" not in reply and EN.disclaimer not in reply


# -- answer_question -------------------------------------------------------------------------


def test_german_refusal_is_german_and_does_not_call_the_model() -> None:
    llm = FakeAnswerLLM(AnswerPayload(answer="x", used_sources=[1], context_sufficient=True))
    result = answer_question(
        None,  # type: ignore[arg-type]
        FakeRetriever([]),
        llm,
        DE_QUESTION,
        min_score=0.3,
        language="de",
    )
    assert result.answer == DE.no_answer and not result.grounded
    assert result.render().endswith(DE.disclaimer)
    assert llm.calls == []


def test_german_dose_referral_replaces_an_answer_with_a_quantity() -> None:
    payload = AnswerPayload(
        answer="Nehmen Sie 400 mg alle sechs Stunden [MedlinePlus: Diabetes].",
        used_sources=[1],
        context_sufficient=True,
    )
    result = answer_question(
        None,  # type: ignore[arg-type]
        FakeRetriever([_candidate()]),
        FakeAnswerLLM(payload),
        DE_QUESTION,
        min_score=0.3,
        language="de",
    )
    assert result.answer == DE.dose_referral and not result.grounded


def test_a_grounded_answer_remembers_its_language() -> None:
    payload = AnswerPayload(
        answer="Symptome sind Durst [MedlinePlus: Diabetes].",
        used_sources=[1],
        context_sufficient=True,
    )
    args = (None, FakeRetriever([_candidate()]), FakeAnswerLLM(payload), DE_QUESTION)
    de = answer_question(*args, min_score=0.3, language="de")  # type: ignore[arg-type]
    assert de.grounded and de.language == "de" and "Quellen:" in de.render()
    en = answer_question(*args, min_score=0.3)  # type: ignore[arg-type]
    assert en.language == "en" and "Sources:" in en.render()


# -- the output guard ------------------------------------------------------------------------


def _guard(draft: str, language: str | None) -> str:
    state: dict[str, object] = {"draft": draft, "draft_kind": "medical"}
    if language is not None:
        state["reply_language"] = language
    message = output_guard_node(state)["messages"][0]  # type: ignore[arg-type]
    return str(message.content)


def test_a_correct_german_reply_passes_the_guard_untouched() -> None:
    reply = _answer("de").render()
    assert _guard(reply, "de") == reply
    assert _guard(reply, "en") == reply  # accepted whatever language the turn thinks it has


def test_the_german_refusal_is_recognised_and_gets_the_german_disclaimer() -> None:
    out = _guard(DE.no_answer, "de")
    assert out == f"{DE.no_answer}\n\n{DE.disclaimer}"


def test_an_uncited_german_answer_is_replaced_in_the_turns_language() -> None:
    uncited = "Diabetes ist eine Stoffwechselerkrankung."
    assert _guard(uncited, "de") == f"{DE.no_answer}\n\n{DE.disclaimer}"
    assert _guard(uncited, "en") == f"{EN.no_answer}\n\n{EN.disclaimer}"
    assert _guard(uncited, None) == f"{EN.no_answer}\n\n{EN.disclaimer}"
    assert _guard(uncited, "tr") == f"{EN.no_answer}\n\n{EN.disclaimer}"  # unknown: English


def test_a_dose_in_a_german_reply_is_replaced_by_the_german_referral() -> None:
    reply = _answer("de").render().replace("Durst", "Durst; nehmen Sie zwei Teelöffel täglich")
    assert _guard(reply, "de") == f"{DE.dose_referral}\n\n{DE.disclaimer}"


def test_a_reply_with_the_other_languages_disclaimer_is_not_given_a_second_one() -> None:
    mixed = _answer("de").render().replace(DE.disclaimer, EN.disclaimer)
    assert _guard(mixed, "de") == mixed


def test_the_disclaimers_themselves_never_count_as_a_dose() -> None:
    # "116 117" and "112" are phone numbers, not quantities
    assert _guard(_answer("de").render(), "de").endswith(DE.disclaimer)


# -- whole turns -----------------------------------------------------------------------------


def _graph(llm: FakeStructuredLLM, payload: AnswerPayload) -> AgentGraph:
    deps = AgentDeps(
        tools=NoTools(),  # type: ignore[arg-type]
        llm=llm,
        answer_llm=FakeAnswerLLM(payload),
        retriever=FakeRetriever([_candidate()]),
        session_factory=lambda: nullcontext(None),  # type: ignore[arg-type,return-value]
        clock=lambda: datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        tz=ZoneInfo("Europe/Berlin"),
        public_only=True,
        rag_min_score=0.7,
    )
    return build_graph(deps, InMemorySaver())


def _decision(language: str) -> RouteDecision:
    return RouteDecision(
        route=Route.MEDICAL_QUESTION,
        is_emergency=False,
        language=language,
        search_query_en=None if language == "en" else "symptoms of diabetes",
    )


GROUNDED = AnswerPayload(
    answer="Symptome sind Durst und Müdigkeit [MedlinePlus: Diabetes].",
    used_sources=[1],
    context_sufficient=True,
)
UNSURE = AnswerPayload(answer="x", used_sources=[1], context_sufficient=False)


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


async def test_a_german_turn_is_answered_with_german_fixed_texts() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_decision("de")]})
    result = await run_turn(_graph(llm, GROUNDED), _thread(), 1, message=DE_QUESTION)
    reply = result.reply or ""
    assert "Quellen:" in reply and f"Inhalt: {ATTRIBUTION}" in reply
    assert reply.endswith(DE.disclaimer)
    assert "[MedlinePlus: Diabetes]" in reply
    assert "Sources:" not in reply and EN.disclaimer not in reply


async def test_a_german_turn_that_cannot_be_answered_refuses_in_german() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_decision("de")]})
    result = await run_turn(_graph(llm, UNSURE), _thread(), 1, message=DE_QUESTION)
    assert result.reply == f"{DE.no_answer}\n\n{DE.disclaimer}"


async def test_another_language_falls_back_to_the_english_texts() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_decision("tr")]})
    result = await run_turn(_graph(llm, UNSURE), _thread(), 1, message="Diyabet nedir?")
    assert result.reply == f"{EN.no_answer}\n\n{EN.disclaimer}"


async def test_the_language_follows_each_turn_and_is_never_stale() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_decision("de"), _decision("en")]})
    graph, thread = _graph(llm, UNSURE), _thread()
    first = await run_turn(graph, thread, 1, message=DE_QUESTION)
    second = await run_turn(graph, thread, 1, message="What are the symptoms of diabetes?")
    assert first.reply == f"{DE.no_answer}\n\n{DE.disclaimer}"
    assert second.reply == f"{EN.no_answer}\n\n{EN.disclaimer}"


# -- the dose guard knows the German forms ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Nehmen Sie zwei Teelöffel täglich.",
        "Einen Esslöffel pro Tag.",
        "Ein Zäpfchen am Abend.",
        "2 Hübe morgens und abends.",
        "Eine Spritze pro Woche.",
        "Zwei Beutel in Wasser auflösen.",
        "Alle vier Stunden 5 Milliliter.",
        "Bis zu 10 Tropfen.",
        "Täglich 400 mg.",
        "Take 5 milliliters twice a day.",
    ],
)
def test_german_doses_are_detected(text: str) -> None:
    assert contains_dose(text)


@pytest.mark.parametrize(
    "text",
    [
        "Erwachsene brauchen 7 bis 9 Stunden Schlaf.",
        "Ein Blutzucker von 100 mg/dL ist normal.",
        "Fieber über 38 Grad dauert oft 2 bis 3 Tage.",
        "Symptome sind starker Durst und Müdigkeit.",
        "Das dauert etwa 2 Wochen.",
        "Diabetes Typ 2 ist die häufigste Form, i.e. oft mit Insulinresistenz verbunden.",
        "Rühren Sie den Teelöffel nicht in die Wunde.",  # no quantity
        "Der Teebeutel ist eine beliebte Hausmittel-Zutat.",
    ],
)
def test_german_measurements_and_ordinary_sentences_are_not_doses(text: str) -> None:
    assert not contains_dose(text)
