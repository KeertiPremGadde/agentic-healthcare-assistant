"""The HTTP API against real Postgres, in process (httpx + ASGI, fake LLM, in-memory checkpointer).

Covers: register/login/JWT, SSE and JSON chat, the booking confirmation round trip over HTTP,
per-user isolation, and the cost protections (rate limits, daily caps, global budget).
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import build_graph
from medagent.agents.schemas import BookingRequest, DoctorQuery, Route, RouteDecision
from medagent.api.limits import ConversationLocks, RateLimiter, UsageStore
from medagent.api.resources import Resources
from medagent.api.routes import chat as chat_routes
from medagent.core.config import Settings
from medagent.db.models import Appointment, AppointmentStatus, DailyUsage, Patient, User
from medagent.db.seed import seed
from medagent.guardrails.emergency import EMERGENCY_MESSAGE
from medagent.main import create_app
from medagent.rag.answer import AnswerPayload
from medagent.schemas.specialty import Specialty
from medagent.tools.clinic import ClinicService, LocalClinicTools
from tests.fakes import FakeAnswerLLM, FakeCalendar, FakeRetriever, FakeStructuredLLM

pytestmark = pytest.mark.integration

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # Monday 09:00 in Berlin
TOMORROW = "2026-11-03"
SECRET = "t" * 48
PASSWORD = "correct-horse-battery"


@dataclass
class Api:
    client: httpx.AsyncClient
    res: Resources
    llm: Any  # FakeStructuredLLM, or the real model in `llm`-marked tests
    calendar: FakeCalendar


ApiFactory = Callable[..., Awaitable[Api]]


@pytest.fixture
async def make_api(engine: Engine, session: Session) -> AsyncIterator[ApiFactory]:
    seed(session)
    clients: list[httpx.AsyncClient] = []

    async def build(delay: float = 0.0, llm: Any = None, **settings_overrides: Any) -> Api:
        defaults: dict[str, Any] = {
            "jwt_secret": SECRET,
            "token_replay_delay_ms": 0,
            "register_rate_per_hour": 100,
            "login_rate_per_minute": 100,
            "chat_rate_per_minute": 100,
        }
        settings = Settings(_env_file=None, **(defaults | settings_overrides))  # type: ignore[call-arg]
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        calendar = FakeCalendar()
        service = ClinicService(sessions, lambda: NOW, BERLIN, 30, calendar)
        tools = LocalClinicTools(service)
        llm = llm or FakeStructuredLLM(delay=delay)
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
        res = Resources(
            settings=settings,
            graph=build_graph(deps, InMemorySaver()),
            clinic=tools,
            session_factory=sessions,
            usage=UsageStore(sessions),
            limiter=RateLimiter(),
            locks=ConversationLocks(),
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(res)), base_url="http://test"
        )
        clients.append(client)
        return Api(client, res, llm, calendar)

    yield build
    for client in clients:
        await client.aclose()


# -- helpers -----------------------------------------------------------------------------
async def signup(api: Api, username: str) -> dict[str, str]:
    """Register + log in; returns the Authorization header."""
    created = await api.client.post(
        "/v1/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert created.status_code == 201, created.text
    token = await api.client.post(
        "/v1/auth/login", data={"username": username, "password": PASSWORD}
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = "".join(line[6:] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


async def stream_events(
    api: Api, path: str, headers: dict[str, str], body: dict[str, Any]
) -> tuple[httpx.Response, list[tuple[str, dict[str, Any]]]]:
    response = await api.client.post(path, headers=headers, json=body)
    return response, parse_sse(response.text)


def script_find_doctor(api: Api) -> None:
    api.llm.push(
        RouteDecision(route=Route.FIND_DOCTOR, is_emergency=False),
        DoctorQuery(specialty=Specialty.CARDIOLOGIST),
    )


def script_book(api: Api, **fields: Any) -> None:
    request = BookingRequest(doctor_option=1, date=TOMORROW, **fields)
    api.llm.push(RouteDecision(route=Route.BOOK, is_emergency=False), request)


def script_smalltalk(api: Api, times: int = 1) -> None:
    for _ in range(times):
        api.llm.push(RouteDecision(route=Route.SMALLTALK, is_emergency=False))


async def chat_json(
    api: Api, headers: dict[str, str], message: str, conversation_id: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return await api.client.post("/v1/chat?stream=false", headers=headers, json=body)


# -- accounts and tokens -----------------------------------------------------------------
async def test_register_login_me_and_the_patient_record(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    created = await api.client.post(
        "/v1/auth/register", json={"username": "Demo-One", "password": PASSWORD}
    )
    assert created.status_code == 201
    assert created.json()["username"] == "demo-one"  # normalised to lower case
    assert PASSWORD not in created.text
    assert "password" not in created.text.lower()

    headers = await signup(api, "second-user")
    me = await api.client.get("/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "second-user"

    session.expire_all()
    user = session.scalars(select(User).where(User.username == "second-user")).one()
    patient = session.get(Patient, user.patient_id)
    assert patient is not None
    assert (patient.email, patient.phone) == (None, None)  # no personal data collected
    assert user.password_hash.startswith("$argon2id$")
    assert me.json()["patient_id"] == user.patient_id


async def test_duplicate_username_is_rejected_case_insensitively(make_api: ApiFactory) -> None:
    api = await make_api()
    await signup(api, "taken-name")
    again = await api.client.post(
        "/v1/auth/register", json={"username": "TAKEN-NAME", "password": PASSWORD}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "username_taken"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("ab", PASSWORD),
        ("has space", PASSWORD),
        ("user@example.com", PASSWORD),
        ("x" * 33, PASSWORD),
        ("valid-name", "short"),
        ("valid-name", "p" * 129),
    ],
)
async def test_invalid_registrations_are_rejected_without_echoing_input(
    make_api: ApiFactory, username: str, password: str
) -> None:
    api = await make_api()
    response = await api.client.post(
        "/v1/auth/register", json={"username": username, "password": password}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert password not in response.text  # FastAPI's default 422 would echo it back
    assert "input" not in response.text


async def test_wrong_password_and_unknown_user_look_identical(make_api: ApiFactory) -> None:
    api = await make_api()
    await signup(api, "real-user")
    wrong = await api.client.post(
        "/v1/auth/login", data={"username": "real-user", "password": "wrong-password-1"}
    )
    unknown = await api.client.post(
        "/v1/auth/login", data={"username": "nobody-here", "password": "wrong-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.headers["WWW-Authenticate"] == "Bearer"


async def test_protected_endpoints_reject_missing_and_bad_tokens(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    await signup(api, "someone")
    user_id = session.scalars(select(User.id)).one()
    soon = datetime.now(UTC)
    claims = {"sub": str(user_id), "iat": soon, "exp": soon + timedelta(hours=1)}
    bad_tokens = {
        "none": None,
        "garbage": "not.a.jwt",
        "wrong-secret": jwt.encode(claims, "w" * 48, algorithm="HS256"),
        "expired": jwt.encode(
            {**claims, "iat": soon - timedelta(hours=3), "exp": soon - timedelta(hours=2)},
            SECRET,
            algorithm="HS256",
        ),
        "alg-none": jwt.encode(claims, key="", algorithm="none"),
        "deleted-user": jwt.encode({**claims, "sub": "999999"}, SECRET, algorithm="HS256"),
    }
    for name, token in bad_tokens.items():
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for method, path in (
            ("GET", "/v1/auth/me"),
            ("GET", "/v1/appointments"),
            ("GET", "/v1/limits"),
        ):
            response = await api.client.request(method, path, headers=headers)
            assert response.status_code == 401, (name, path)
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.json()["error"]["code"] in {"not_authenticated", "invalid_token"}
    chat = await api.client.post("/v1/chat", json={"message": "hi"})
    assert chat.status_code == 401


async def test_every_endpoint_except_register_login_and_health_requires_auth(
    make_api: ApiFactory,
) -> None:
    api = await make_api()
    spec = (await api.client.get("/openapi.json")).json()
    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]  # /docs Authorize
    open_paths = {"/health", "/ready", "/v1/auth/register", "/v1/auth/login"}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            assert bool(operation.get("security")) or path in open_paths, f"{method} {path}"


async def test_register_and_login_are_rate_limited_per_ip(make_api: ApiFactory) -> None:
    api = await make_api(register_rate_per_hour=2, login_rate_per_minute=3)
    for i in range(2):
        ok = await api.client.post(
            "/v1/auth/register", json={"username": f"user-{i}-aa", "password": PASSWORD}
        )
        assert ok.status_code == 201
    blocked = await api.client.post(
        "/v1/auth/register", json={"username": "user-3-aa", "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1

    for _ in range(3):
        await api.client.post(
            "/v1/auth/login", data={"username": "user-0-aa", "password": "x" * 12}
        )
    guessing = await api.client.post(
        "/v1/auth/login", data={"username": "user-0-aa", "password": PASSWORD}
    )
    assert guessing.status_code == 429  # even the right password: the guesses were the problem


# -- chat: JSON and SSE -------------------------------------------------------------------------
async def test_chat_json_returns_reply_conversation_id_and_usage(make_api: ApiFactory) -> None:
    api = await make_api()
    headers = await signup(api, "chatter")
    script_smalltalk(api)
    response = await chat_json(api, headers, "hello")
    assert response.status_code == 200
    body = response.json()
    assert len(body["conversation_id"]) == 32
    assert "I'm MedAgent" in body["reply"]
    assert body["pending"] is None
    assert body["kind"] == "normal"
    assert body["appointment_id"] is None
    assert body["booking"] is None
    assert body["doctors"] is None  # only a reply that suggests doctors carries them
    assert {"input_tokens", "output_tokens", "est_cost_usd"} <= body["usage"].keys()
    assert response.headers["X-Request-ID"]


async def test_chat_stream_event_order_and_token_replay(make_api: ApiFactory) -> None:
    api = await make_api()
    headers = await signup(api, "streamer")
    script_find_doctor(api)
    response, events = await stream_events(
        api, "/v1/chat", headers, {"message": "palpitations on stairs, which doctor?"}
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Request-ID"]
    names = [name for name, _ in events]
    assert names[0] == "step"
    assert names[-1] == "done"
    assert names[-2] == "message"
    assert set(names) == {"step", "token", "message", "done"}
    assert [d["node"] for n, d in events if n == "step"] == ["supervisor", "doctor_finder"]
    assert [d["label"] for n, d in events if n == "step"][1] == "Looking for suitable doctors…"
    tokens = "".join(d["text"] for n, d in events if n == "token")
    message = next(d["text"] for n, d in events if n == "message")
    assert tokens == message  # the replayed chunks are exactly the final message
    assert "Cardiologist" in message
    # The options arrive as data, so the UI can render cards and a Book button per doctor.
    doctors = next(d for n, d in events if n == "message")["doctors"]
    assert doctors
    assert {"id", "name", "specialty", "city", "languages"} == set(doctors[0])
    assert all(d["specialty"] == "Cardiologist" for d in doctors)
    assert all(d["name"] in message for d in doctors)  # same doctors, same order as the text
    done = events[-1][1]
    assert done["pending"] is False
    assert len(done["conversation_id"]) == 32


async def test_booking_confirmation_round_trip_over_http(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    headers = await signup(api, "booker")
    script_find_doctor(api)
    first = (await chat_json(api, headers, "chest tightness on stairs, which doctor?")).json()
    conversation = first["conversation_id"]

    script_book(api, time_of_day="afternoon")
    paused = (await chat_json(api, headers, "book number 1", conversation)).json()
    assert paused["reply"] is None
    assert paused["pending"]["type"] == "confirm_booking"
    assert paused["pending"]["question"] == (
        "Shall I book Tue 3 Nov 2026, 13:00 with Dr. Michael Johnson?"
    )
    assert (await api.client.get("/v1/appointments", headers=headers)).json() == []  # not yet

    history = (await api.client.get(f"/v1/chat/{conversation}", headers=headers)).json()
    assert history["pending"]["type"] == "confirm_booking"  # a reloaded page can restore it
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user"]

    done = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=headers, json={"confirmed": True}
    )
    assert done.status_code == 200
    assert done.json()["reply"].startswith("Booked: Dr. Michael Johnson, Tue 3 Nov 2026, 13:00")

    mine = (await api.client.get("/v1/appointments", headers=headers)).json()
    assert [(a["doctor_name"], a["status"]) for a in mine] == [("Dr. Michael Johnson", "booked")]
    assert len(api.calendar.added) == 1

    # A second resume must not book again.
    again = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=headers, json={"confirmed": True}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "nothing_to_confirm"

    cancelled = await api.client.delete(f"/v1/appointments/{mine[0]['id']}", headers=headers)
    assert cancelled.status_code == 204
    assert api.calendar.removed == [mine[0]["id"]]
    assert (await api.client.get("/v1/appointments", headers=headers)).json() == []
    twice = await api.client.delete(f"/v1/appointments/{mine[0]['id']}", headers=headers)
    assert twice.status_code == 409
    session.expire_all()
    assert session.scalars(select(Appointment)).one().status is AppointmentStatus.CANCELLED


async def test_sse_confirmation_event_and_resume_stream(make_api: ApiFactory) -> None:
    api = await make_api()
    headers = await signup(api, "sse-booker")
    script_find_doctor(api)
    conversation = (await chat_json(api, headers, "palpitations, which doctor?")).json()[
        "conversation_id"
    ]
    script_book(api)
    _, events = await stream_events(
        api, "/v1/chat", headers, {"message": "book number 1", "conversation_id": conversation}
    )
    names = [n for n, _ in events]
    assert names[-2:] == ["confirmation", "done"]
    assert "message" not in names
    assert events[-1][1]["pending"] is True
    assert events[-2][1]["type"] == "confirm_booking"

    _, resumed = await stream_events(
        api, f"/v1/chat/{conversation}/resume", headers, {"confirmed": True}
    )
    assert [d["node"] for n, d in resumed if n == "step"] == ["book_appointment"]
    final = next(d for n, d in resumed if n == "message")
    assert final["text"].startswith("Booked:")
    assert final["kind"] == "booked"  # lets the UI show the green card and the .ics button
    assert "doctors" not in final  # the doctor list belongs to the turn that suggested them
    booking = final["booking"]
    assert set(booking) == {"appointment_id", "doctor", "start"}
    assert booking["appointment_id"] == final["appointment_id"]
    assert booking["doctor"] in final["text"]
    assert booking["start"] in final["text"]
    assert (
        final["appointment_id"]
        == (await api.client.get("/v1/appointments", headers=headers)).json()[0]["id"]
    )


async def test_declining_a_confirmation_books_nothing(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    headers = await signup(api, "decliner")
    script_find_doctor(api)
    conversation = (await chat_json(api, headers, "palpitations, which doctor?")).json()[
        "conversation_id"
    ]
    script_book(api)
    await chat_json(api, headers, "book number 1", conversation)
    no = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=headers, json={"confirmed": False}
    )
    assert no.json()["reply"] == "No problem. Which other day or time would suit you?"
    assert session.scalars(select(Appointment)).first() is None


# -- isolation between users -------------------------------------------------------------
async def test_users_cannot_touch_each_others_conversations_or_appointments(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    alice = await signup(api, "alice-aaa")
    bob = await signup(api, "bob-bbbb")

    script_find_doctor(api)
    conversation = (await chat_json(api, alice, "palpitations, which doctor?")).json()[
        "conversation_id"
    ]
    script_book(api)
    await chat_json(api, alice, "book number 1", conversation)  # alice has a pending confirmation

    # Bob can neither read nor resume alice's conversation: for him it does not exist.
    assert (await api.client.get(f"/v1/chat/{conversation}", headers=bob)).status_code == 404
    resume = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=bob, json={"confirmed": True}
    )
    assert resume.status_code == 404
    assert session.scalars(select(Appointment)).first() is None  # nothing was booked

    # Bob posting with alice's conversation id starts HIS OWN conversation under that id.
    script_smalltalk(api)
    await chat_json(api, bob, "hello", conversation)
    alice_history = (await api.client.get(f"/v1/chat/{conversation}", headers=alice)).json()
    assert alice_history["pending"] is not None
    assert [m["role"] for m in alice_history["messages"]] == ["user", "assistant", "user"]

    # Alice confirms; only alice sees and can cancel the appointment.
    await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=alice, json={"confirmed": True}
    )
    appointment_id = (await api.client.get("/v1/appointments", headers=alice)).json()[0]["id"]
    assert (await api.client.get("/v1/appointments", headers=bob)).json() == []
    assert (
        await api.client.delete(f"/v1/appointments/{appointment_id}", headers=bob)
    ).status_code == 404
    session.expire_all()
    assert session.scalars(select(Appointment)).one().status is AppointmentStatus.BOOKED


async def test_the_patient_comes_from_the_token_not_the_request(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api()
    headers = await signup(api, "honest-user")
    other_patient = session.scalars(select(Patient.id).order_by(Patient.id)).first()
    my_patient = (await api.client.get("/v1/auth/me", headers=headers)).json()["patient_id"]
    assert other_patient != my_patient

    script_find_doctor(api)
    script_book(api)
    spoof = {"message": "x", "patient_id": other_patient, "user_id": 1}
    first = await api.client.post(
        "/v1/chat?stream=false",
        headers=headers,
        json=spoof | {"message": "palpitations, which doctor?"},
    )
    conversation = first.json()["conversation_id"]
    await api.client.post(
        "/v1/chat?stream=false",
        headers=headers,
        json=spoof | {"message": "book number 1", "conversation_id": conversation},
    )
    await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false",
        headers=headers,
        json={"confirmed": True, "patient_id": other_patient},
    )
    assert session.scalars(select(Appointment)).one().patient_id == my_patient


# -- request validation ------------------------------------------------------------------
async def test_message_validation(make_api: ApiFactory) -> None:
    api = await make_api(max_message_chars=50)
    headers = await signup(api, "validator")
    too_long = await chat_json(api, headers, "x" * 51)
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "message_too_long"
    for blank in ("", "   \n\t "):
        assert (await chat_json(api, headers, blank)).status_code == 422
    bad_id = await chat_json(api, headers, "hi", "not-a-valid-id")
    assert bad_id.status_code == 422
    assert llm_not_called(api)


def llm_not_called(api: Api) -> bool:
    return api.llm.calls == []


async def test_unknown_or_malformed_conversation_ids_are_404(make_api: ApiFactory) -> None:
    api = await make_api()
    headers = await signup(api, "explorer")
    for cid in (uuid.uuid4().hex, "short", "../../etc/passwd", "G" * 32):
        assert (await api.client.get(f"/v1/chat/{cid}", headers=headers)).status_code == 404
        resumed = await api.client.post(
            f"/v1/chat/{cid}/resume?stream=false", headers=headers, json={"confirmed": True}
        )
        assert resumed.status_code == 404


async def test_resume_with_nothing_pending_is_a_conflict(make_api: ApiFactory) -> None:
    api = await make_api()
    headers = await signup(api, "idle-user")
    script_smalltalk(api)
    conversation = (await chat_json(api, headers, "hello")).json()["conversation_id"]
    response = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=headers, json={"confirmed": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "nothing_to_confirm"


async def test_a_busy_conversation_answers_409_and_frees_up_afterwards(
    make_api: ApiFactory,
) -> None:
    api = await make_api()
    headers = await signup(api, "busy-user")
    script_smalltalk(api, 2)
    conversation = uuid.uuid4().hex
    user_id = (await api.client.get("/v1/auth/me", headers=headers)).json()  # noqa: F841
    thread = f"u{_user_id(api, 'busy-user')}:{conversation}"
    assert api.res.locks.try_acquire(thread)  # another turn is "running"
    busy = await chat_json(api, headers, "hello", conversation)
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "conversation_busy"
    assert api.llm.calls == []
    api.res.locks.release(thread)
    assert (await chat_json(api, headers, "hello", conversation)).status_code == 200
    assert api.res.locks.try_acquire(thread)  # the lock was released after the turn


def _user_id(api: Api, username: str) -> int:
    with api.res.session_factory() as session:
        return session.scalars(select(User.id).where(User.username == username)).one()


async def test_chat_is_rate_limited_per_user(make_api: ApiFactory) -> None:
    api = await make_api(chat_rate_per_minute=2)
    one, two = await signup(api, "fast-user"), await signup(api, "other-user")
    script_smalltalk(api, 4)
    assert (await chat_json(api, one, "hi")).status_code == 200
    assert (await chat_json(api, one, "hi")).status_code == 200
    limited = await chat_json(api, one, "hi")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert (await chat_json(api, two, "hi")).status_code == 200  # another user is unaffected


# -- cost protection ---------------------------------------------------------------------
async def test_daily_message_limit_blocks_chat_but_not_confirmations(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api(daily_message_limit=2)
    headers = await signup(api, "capped-user")
    script_find_doctor(api)
    conversation = (await chat_json(api, headers, "palpitations, which doctor?")).json()[
        "conversation_id"
    ]
    script_book(api)
    await chat_json(api, headers, "book number 1", conversation)  # message 2: pending booking

    limits = (await api.client.get("/v1/limits", headers=headers)).json()
    assert (limits["messages_used_today"], limits["daily_message_limit"]) == (2, 2)
    assert "synthetic data" in limits["demo_notice"]

    calls_before = len(api.llm.calls)
    blocked = await chat_json(api, headers, "one more question", conversation)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "demo_limit_reached"
    assert "message limit" in blocked.json()["error"]["message"]
    assert int(blocked.headers["Retry-After"]) > 0
    assert len(api.llm.calls) == calls_before  # no LLM call was made

    # Confirming costs nothing (no LLM), so a pending booking can still be completed.
    done = await api.client.post(
        f"/v1/chat/{conversation}/resume?stream=false", headers=headers, json={"confirmed": True}
    )
    assert done.status_code == 200
    assert done.json()["reply"].startswith("Booked:")


async def test_global_budget_stops_all_llm_calls_for_everyone(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api(daily_budget_usd=1.00)
    headers = await signup(api, "latecomer")
    # Other accounts already spent the whole budget today.
    spender = User(
        username="big-spender",
        password_hash="x",
        patient_id=session.scalars(select(Patient.id)).first(),
    )
    session.add(spender)
    session.commit()
    api.res.usage.add_cost(spender.id, 0.60)
    api.res.usage.add_cost(spender.id, 0.40)
    assert api.res.usage.global_spend_today() == Decimal("1.000000")

    script_smalltalk(api)
    blocked = await chat_json(api, headers, "hello")
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "demo_limit_reached"
    assert "demo limit for today" in blocked.json()["error"]["message"]
    assert int(blocked.headers["Retry-After"]) > 0
    assert api.llm.calls == []  # no LLM call was made

    streamed = await api.client.post("/v1/chat", headers=headers, json={"message": "hello"})
    assert streamed.status_code == 503  # same for streaming


async def test_emergency_messages_are_still_answered_when_a_limit_is_reached(
    make_api: ApiFactory, session: Session
) -> None:
    api = await make_api(daily_budget_usd=0.01)
    headers = await signup(api, "worried-user")
    other = User(
        username="spender-two",
        password_hash="x",
        patient_id=session.scalars(select(Patient.id)).first(),
    )
    session.add(other)
    session.commit()
    api.res.usage.add_cost(other.id, 5.0)  # far over budget

    response = await chat_json(api, headers, "I have crushing chest pain and can't breathe")
    assert response.status_code == 200  # not a limit error
    assert response.json()["reply"] == EMERGENCY_MESSAGE
    assert response.json()["kind"] == "emergency"
    streamed = await api.client.post(
        "/v1/chat", headers=headers, json={"message": "Mein Vater ist bewusstlos"}
    )
    assert streamed.status_code == 200
    assert [n for n, _ in parse_sse(streamed.text)] == ["message", "done"]
    assert api.llm.calls == []  # still no LLM: the rules answered
    # ...but an ordinary message is limited.
    assert (await chat_json(api, headers, "hello")).status_code == 503


async def test_harmful_messages_get_the_fixed_reply_not_a_limit_error_when_a_limit_is_reached(
    make_api: ApiFactory, session: Session
) -> None:
    from medagent.guardrails.harmful import HARMFUL_MESSAGE
    from medagent.guardrails.texts import DE

    api = await make_api(daily_budget_usd=0.01)
    headers = await signup(api, "limit-and-crisis")
    other = User(
        username="spender-three",
        password_hash="x",
        patient_id=session.scalars(select(Patient.id)).first(),
    )
    session.add(other)
    session.commit()
    api.res.usage.add_cost(other.id, 5.0)  # far over budget: ordinary chat is refused

    harmful = "How many sleeping tablets to kill a person?"
    json_reply = await chat_json(api, headers, harmful)
    assert json_reply.status_code == 200  # not "demo limit reached"
    assert json_reply.json()["reply"] == HARMFUL_MESSAGE
    streamed = await api.client.post("/v1/chat", headers=headers, json={"message": harmful})
    assert streamed.status_code == 200
    events = parse_sse(streamed.text)
    assert [n for n, _ in events] == ["message", "done"]
    assert events[0][1]["text"] == HARMFUL_MESSAGE
    assert events[0][1]["kind"] == "harmful_intent"  # shown as a crisis card, not a red alarm
    german = await chat_json(api, headers, "Was ist die tödliche Dosis von Paracetamol?")
    assert german.json()["reply"] == DE.harmful_message  # the rule that matched was German
    assert api.llm.calls == []  # still no LLM call
    assert (await chat_json(api, headers, "hello")).status_code == 503  # ordinary chat: limited


async def test_usage_is_counted_per_user_and_day(make_api: ApiFactory, session: Session) -> None:
    api = await make_api()
    headers = await signup(api, "counted-user")
    script_smalltalk(api, 2)
    await chat_json(api, headers, "hi")
    await chat_json(api, headers, "hi again")
    uid = _user_id(api, "counted-user")
    assert api.res.usage.messages_today(uid) == 2
    session.expire_all()
    row = session.scalars(select(DailyUsage).where(DailyUsage.user_id == uid)).one()
    assert row.messages == 2
    assert row.day == datetime.now(UTC).date()


# -- streaming robustness ----------------------------------------------------------------
async def test_keepalive_comments_are_sent_while_a_slow_turn_runs(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_routes, "KEEPALIVE_SECONDS", 0.05)
    api = await make_api(delay=0.3)  # a slow model
    headers = await signup(api, "patient-user")
    script_smalltalk(api)
    response = await api.client.post("/v1/chat", headers=headers, json={"message": "hello"})
    assert response.text.count(": keepalive") >= 2
    assert [n for n, _ in parse_sse(response.text)][-1] == "done"


async def test_an_abandoned_stream_releases_the_conversation_lock(make_api: ApiFactory) -> None:
    api = await make_api(delay=0.2)
    headers = await signup(api, "dropper")
    user_id = _user_id(api, "dropper")
    me = (await api.client.get("/v1/auth/me", headers=headers)).json()
    conversation = uuid.uuid4().hex
    thread = f"u{user_id}:{conversation}"
    script_smalltalk(api)
    assert api.res.locks.try_acquire(thread)
    user = chat_routes.CurrentUser(user_id, "dropper", me["patient_id"])
    stream = chat_routes._stream(api.res, user, thread, conversation, message="hello")
    first = await anext(stream)  # a step event: the turn is running
    assert first.startswith(b"event: step")
    await stream.aclose()  # the client disconnected
    assert api.res.locks.try_acquire(thread)  # the lock is free again


# -- misc endpoints ----------------------------------------------------------------------
async def test_error_envelope_and_request_id(make_api: ApiFactory) -> None:
    api = await make_api()
    missing = await api.client.get("/nope", headers={"X-Request-ID": "trace-abcdef12"})
    assert missing.status_code == 404
    body = missing.json()["error"]
    assert body["code"] == "not_found"
    assert body["request_id"] == "trace-abcdef12" == missing.headers["X-Request-ID"]
    wrong_method = await api.client.put("/health")
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


async def test_health_ready_and_cors(make_api: ApiFactory) -> None:
    api = await make_api()
    assert (await api.client.get("/health")).json()["status"] == "ok"
    assert (await api.client.get("/ready")).json() == {"status": "ready"}
    allowed = await api.client.options(
        "/v1/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in allowed.headers  # no cookies: Bearer only
    denied = await api.client.options(
        "/v1/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers


async def test_demo_page_is_served_in_local_mode_only(make_api: ApiFactory) -> None:
    api = await make_api()
    page = await api.client.get("/demo")
    assert page.status_code == 200
    assert "synthetic data" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "innerHTML" not in page.text  # model output is only ever inserted as text

    hidden = Settings(_env_file=None, app_env="production", jwt_secret="p" * 48)  # type: ignore[call-arg, arg-type]
    prod = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(api.res.__class__(**{**api.res.__dict__, "settings": hidden}))
        ),
        base_url="http://test",
    )
    async with prod:
        assert (await prod.get("/demo")).status_code == 404


@pytest.mark.llm
async def test_real_model_through_the_api_costs_a_fraction_of_a_cent(
    make_api: ApiFactory,
) -> None:
    """Run with `pytest -m llm`: real Claude behind the real HTTP layer (JSON and SSE)."""
    from medagent.agents.llm import AnthropicStructuredLLM
    from medagent.core.config import get_settings

    if get_settings().anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    api = await make_api(llm=AnthropicStructuredLLM())
    headers = await signup(api, "llm-user")

    found = (
        await chat_json(
            api, headers, "I've had an itchy red rash on my arm for a week. Who should I see?"
        )
    ).json()
    assert "Dermatologist" in found["reply"]
    assert 0 < found["usage"]["est_cost_usd"] < 0.01

    _, events = await stream_events(
        api, "/v1/chat", headers, {"message": "Hi, what can you do?", "conversation_id": None}
    )
    names = [n for n, _ in events]
    assert names[0] == "step"
    assert names[-1] == "done"
    assert "".join(d["text"] for n, d in events if n == "token") == next(
        d["text"] for n, d in events if n == "message"
    )


async def test_doctor_options_are_returned_as_data_in_json_mode_and_only_for_that_turn(
    make_api: ApiFactory,
) -> None:
    api = await make_api()
    headers = await signup(api, "card-user")
    script_find_doctor(api)
    first = (await chat_json(api, headers, "palpitations, which doctor?")).json()
    assert [d["specialty"] for d in first["doctors"]] == ["Cardiologist"] * len(first["doctors"])
    assert first["doctors"][0]["name"] in first["reply"]

    script_smalltalk(api)  # the options stay in the conversation memory, but are not re-sent
    later = (await chat_json(api, headers, "thanks!", first["conversation_id"])).json()
    assert later["doctors"] is None
