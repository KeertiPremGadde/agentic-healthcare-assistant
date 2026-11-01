"""Real Claude calls through the graph's structured outputs. Run with: uv run pytest -m llm

Uses LLM_MODEL from settings (claude-haiku-5-5 in development). Each test asserts that a turn
costs well under a cent, so a pricing or effort mistake shows up here.
"""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import build_graph
from medagent.agents.llm import AnthropicStructuredLLM
from medagent.agents.prompts.booking import BOOKING_SYSTEM_PROMPT, DOCTOR_FINDER_SYSTEM_PROMPT
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT
from medagent.agents.runner import run_turn
from medagent.agents.schemas import BookingRequest, DoctorQuery, Route, RouteDecision
from medagent.core.config import get_settings
from medagent.db.models import Appointment, Patient
from medagent.db.seed import seed
from medagent.rag.answer import AnswerPayload
from medagent.schemas.specialty import Specialty
from medagent.tools.clinic import ClinicService, LocalClinicTools
from tests.fakes import FakeAnswerLLM, FakeRetriever

pytestmark = [pytest.mark.integration, pytest.mark.llm]

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # Monday


@pytest.fixture(scope="module")
def llm() -> AnthropicStructuredLLM:
    if get_settings().anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return AnthropicStructuredLLM()


@pytest.mark.parametrize(
    ("message", "route"),
    [
        ("What causes migraines?", Route.MEDICAL_QUESTION),
        ("I've had an itchy rash on my arm for a week, who should I see?", Route.FIND_DOCTOR),
        ("I'd like to book an appointment with Dr. Wilson on Friday", Route.BOOK),
        ("Please cancel my appointment next week", Route.CANCEL),
        ("Which hospitals are there near Hamburg?", Route.NEARBY_CLINICS),
        ("Hi there, what can you do?", Route.SMALLTALK),
        ("Write me a poem about the sea", Route.OUT_OF_SCOPE),
    ],
)
async def test_router_classifies_with_structured_output(
    llm: AnthropicStructuredLLM, message: str, route: Route
) -> None:
    decision = await llm.ainvoke(
        RouteDecision, ROUTER_SYSTEM_PROMPT.format(context="None."), [HumanMessage(message)]
    )
    assert decision.route is route
    assert decision.is_emergency is False


@pytest.mark.parametrize(
    ("message", "specialty"),
    [
        ("I've had an itchy red rash on my arm for a week", Specialty.DERMATOLOGIST),
        ("My back tooth hurts when I drink something cold", Specialty.DENTIST),
    ],
)
async def test_doctor_finder_picks_a_specialty_from_the_enum(
    llm: AnthropicStructuredLLM, message: str, specialty: Specialty
) -> None:
    query = await llm.ainvoke(DoctorQuery, DOCTOR_FINDER_SYSTEM_PROMPT, [HumanMessage(message)])
    assert query.specialty is specialty


async def test_booking_extraction_resolves_relative_dates(llm: AnthropicStructuredLLM) -> None:
    prompt = BOOKING_SYSTEM_PROMPT.format(
        today="2026-11-02",
        today_weekday="Monday",
        timezone="Europe/Berlin",
        options="1. Dr. Michael Johnson (Cardiologist)\n2. Dr. Sarah Wilson (Cardiologist)",
        current_doctor="none",
    )
    request = await llm.ainvoke(
        BookingRequest, prompt, [HumanMessage("Book number 2 on Thursday afternoon please")]
    )
    assert request.doctor_option == 2
    assert request.date == "2026-11-05"
    assert request.time_of_day == "afternoon"
    assert request.exact_time is None


@pytest.mark.parametrize(
    ("message", "language", "has_query"),
    [
        ("What are the symptoms of diabetes?", "en", False),
        ("Was sind die Symptome von Diabetes?", "de", True),
        ("Wie wird Bluthochdruck behandelt?", "de", True),
        ("Diyabetin belirtileri nelerdir?", "tr", True),
    ],
)
async def test_router_reports_the_language_and_an_english_query_only_for_other_languages(
    llm: AnthropicStructuredLLM, message: str, language: str, has_query: bool
) -> None:
    decision = await llm.ainvoke(
        RouteDecision, ROUTER_SYSTEM_PROMPT.format(context="None."), [HumanMessage(message)]
    )
    assert decision.route is Route.MEDICAL_QUESTION
    assert decision.language.lower().split("-")[0] == language
    assert (decision.english_search_query() is not None) is has_query


async def test_a_german_question_gets_german_fixed_texts_end_to_end(
    llm: AnthropicStructuredLLM,
) -> None:
    from contextlib import nullcontext

    from medagent.guardrails.texts import DE, EN
    from tests.fakes import NoTools

    deps = AgentDeps(
        tools=NoTools(),  # type: ignore[arg-type]  (a medical question never uses the tools)
        llm=llm,
        answer_llm=FakeAnswerLLM(
            AnswerPayload(answer="x", used_sources=[], context_sufficient=False)
        ),
        retriever=FakeRetriever(),
        session_factory=lambda: nullcontext(None),  # type: ignore[arg-type,return-value]
        clock=lambda: NOW,
        tz=BERLIN,
        public_only=True,
        rag_min_score=0.7,
    )
    graph = build_graph(deps, InMemorySaver())
    # no evidence is found, so the pipeline refuses without calling the answer model
    result = await run_turn(graph, f"llm-{uuid.uuid4().hex[:8]}", 1, message="Was ist Gicht?")
    assert result.reply == f"{DE.no_answer}\n\n{DE.disclaimer}"
    assert EN.disclaimer not in (result.reply or "")
    assert result.cost.usd < 0.01


async def test_full_conversation_finds_a_doctor_and_books_with_confirmation(
    llm: AnthropicStructuredLLM, engine: Engine, session: Session
) -> None:
    seed(session)
    patient = session.scalars(select(Patient).order_by(Patient.id)).first()
    assert patient is not None
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tools = LocalClinicTools(ClinicService(sessions, lambda: NOW, BERLIN, 30))
    deps = AgentDeps(
        tools=tools,
        llm=llm,
        answer_llm=FakeAnswerLLM(
            AnswerPayload(answer="x", used_sources=[], context_sufficient=False)
        ),
        retriever=FakeRetriever(),
        session_factory=sessions,
        clock=lambda: NOW,
        tz=BERLIN,
        public_only=True,
        rag_min_score=0.7,
    )
    graph, thread = build_graph(deps, InMemorySaver()), f"llm-{uuid.uuid4().hex[:8]}"

    found = await run_turn(
        graph,
        thread,
        patient.id,
        message="I've had an itchy red rash on my arm for a week. Who should I see?",
    )
    assert found.reply is not None
    assert "Dermatologist" in found.reply
    assert found.cost.usd < 0.01

    paused = await run_turn(graph, thread, patient.id, message="Book number 1 tomorrow morning")
    assert paused.pending is not None, paused.reply
    assert "Tue 3 Nov 2026" in paused.pending["question"]
    assert paused.cost.usd < 0.01

    done = await run_turn(graph, thread, patient.id, resume=True)
    assert done.reply is not None
    assert done.reply.startswith("Booked:")
    session.expire_all()
    appointment = session.scalars(select(Appointment)).one()
    assert appointment.start_time.astimezone(BERLIN).hour < 12  # a morning slot
