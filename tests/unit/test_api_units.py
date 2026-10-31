"""API building blocks that need no database: passwords, JWTs, limiter, locks, SSE, settings."""

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from medagent.api.limits import (
    ConversationLocks,
    RateLimiter,
    seconds_until_next_utc_day,
)
from medagent.api.middleware import RequestIdMiddleware
from medagent.api.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from medagent.api.sse import STEP_LABELS, chunk_text, keepalive, sse
from medagent.core.config import Settings

SECRET = "s" * 48


# ------------------------------------------------------------------ passwords
def test_passwords_are_argon2_hashed_and_verified() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert "correct-horse" not in hashed
    assert verify_password("correct-horse-battery", hashed)
    assert not verify_password("wrong-password-123", hashed)


def test_same_password_hashes_differently_each_time() -> None:
    assert hash_password("correct-horse-battery") != hash_password("correct-horse-battery")


def test_unknown_user_still_runs_a_verification_and_fails() -> None:
    assert verify_password("anything-at-all", None) is False  # no hash: constant-effort failure


# ------------------------------------------------------------------ tokens
def test_token_roundtrip_carries_only_the_user_id() -> None:
    token = create_access_token(42, SECRET, 60)
    assert decode_access_token(token, SECRET) == 42
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp"}  # no patient id, no username, no roles


def test_expired_token_is_rejected() -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    token = create_access_token(1, SECRET, 60, now=old)
    with pytest.raises(InvalidTokenError, match="ExpiredSignatureError"):
        decode_access_token(token, SECRET)


def test_wrong_secret_and_tampered_tokens_are_rejected() -> None:
    token = create_access_token(1, SECRET, 60)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, "another-secret-entirely-" + "x" * 30)
    header, payload, signature = token.split(".")
    flipped = signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{payload}.{flipped}", SECRET)


def test_alg_none_token_is_rejected() -> None:
    unsigned = jwt.encode(
        {"sub": "1", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, SECRET)


def test_token_signed_with_another_algorithm_is_rejected() -> None:
    claims = {"sub": "1", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)}
    with pytest.raises(InvalidTokenError):
        decode_access_token(jwt.encode(claims, "k" * 64, algorithm="HS512"), SECRET)


@pytest.mark.parametrize("missing", ["exp", "sub", "iat"])
def test_token_missing_a_required_claim_is_rejected(missing: str) -> None:
    claims = {"sub": "1", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)}
    del claims[missing]
    with pytest.raises(InvalidTokenError):
        decode_access_token(jwt.encode(claims, SECRET, algorithm="HS256"), SECRET)


def test_garbage_and_non_numeric_subject_are_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", SECRET)
    claims = {
        "sub": "admin",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    with pytest.raises(InvalidTokenError):
        decode_access_token(jwt.encode(claims, SECRET, algorithm="HS256"), SECRET)


# ------------------------------------------------------------------ rate limiter
def test_rate_limiter_allows_the_limit_then_blocks_until_the_window_passes() -> None:
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert [limiter.allow("k", 3, 60)[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.allow("k", 3, 60)
    assert not allowed
    assert retry_after == pytest.approx(60)
    now[0] = 30
    assert limiter.allow("k", 3, 60)[1] == pytest.approx(30)  # still blocked, less to wait
    now[0] = 61
    assert limiter.allow("k", 3, 60)[0]  # the first hits expired


def test_rate_limiter_keys_are_independent() -> None:
    limiter = RateLimiter(clock=lambda: 0.0)
    assert limiter.allow("ip:1", 1, 60)[0]
    assert not limiter.allow("ip:1", 1, 60)[0]
    assert limiter.allow("ip:2", 1, 60)[0]


# ------------------------------------------------------------------ conversation locks
def test_conversation_lock_is_exclusive_and_released() -> None:
    locks = ConversationLocks()
    assert locks.try_acquire("u1:a")
    assert not locks.try_acquire("u1:a")
    assert locks.try_acquire("u1:b")
    locks.release("u1:a")
    assert locks.try_acquire("u1:a")
    locks.release("never-held")  # harmless


def test_stale_conversation_lock_can_be_taken_again() -> None:
    now = [0.0]
    locks = ConversationLocks(max_age_seconds=300, clock=lambda: now[0])
    assert locks.try_acquire("k")
    now[0] = 299
    assert not locks.try_acquire("k")
    now[0] = 301  # the holder is long gone (an abandoned stream)
    assert locks.try_acquire("k")


def test_seconds_until_midnight_utc() -> None:
    assert seconds_until_next_utc_day(datetime(2026, 11, 2, 23, 59, 0, tzinfo=UTC)) == 60
    assert seconds_until_next_utc_day(datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)) == 86_400


# ------------------------------------------------------------------ SSE
def test_sse_event_format() -> None:
    frame = sse("step", {"node": "booking", "label": "Checking availability…"}).decode()
    assert frame.startswith("event: step\ndata: ")
    assert frame.endswith("\n\n")
    data = json.loads(frame.split("data: ", 1)[1])
    assert data["label"] == "Checking availability…"  # unicode is not escaped away


def test_sse_event_with_newlines_in_text_stays_one_data_line() -> None:
    frame = sse("message", {"text": "line one\nline two"}).decode()
    assert frame.count("data:") == 1  # JSON escapes the newline, so the frame can't be split
    assert json.loads(frame.split("data: ", 1)[1])["text"] == "line one\nline two"


def test_keepalive_is_a_comment() -> None:
    assert keepalive().decode().startswith(":")


@pytest.mark.parametrize(
    "text",
    [
        "Hello there, how can I help you today?",
        "  leading spaces and\nnewlines\n\nand trailing   ",
        "one",
        "Sources:\n- MedlinePlus: Diabetes <https://medlineplus.gov/diabetes.html>\n\nDisclaimer.",
    ],
)
def test_chunks_join_back_to_the_exact_text(text: str) -> None:
    chunks = chunk_text(text, words_per_chunk=3)
    assert "".join(chunks) == text
    assert all(len(c.split()) <= 3 for c in chunks)


def test_empty_text_has_no_chunks() -> None:
    assert chunk_text("") == []


def test_step_labels_name_real_graph_nodes() -> None:
    from medagent.agents.graph import build_graph  # noqa: F401  (import check)
    from tests.fakes import FakeStructuredLLM
    from tests.unit.test_agent_graph import _graph

    nodes = set(_graph(FakeStructuredLLM()).get_graph().nodes)
    assert set(STEP_LABELS) <= nodes


# ------------------------------------------------------------------ settings
def test_non_local_environment_refuses_the_placeholder_or_a_short_secret() -> None:
    for secret in ("change-me", "short"):
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings(_env_file=None, app_env="production", jwt_secret=secret)  # type: ignore[call-arg, arg-type]
    ok = Settings(_env_file=None, app_env="production", jwt_secret="x" * 40)  # type: ignore[call-arg, arg-type]
    assert ok.app_env == "production"


def test_local_environment_accepts_the_placeholder() -> None:
    assert Settings(_env_file=None).jwt_secret.get_secret_value() == "change-me"  # type: ignore[call-arg]


def test_secret_is_not_printed_in_settings_repr() -> None:
    settings = Settings(_env_file=None, jwt_secret="x" * 40)  # type: ignore[call-arg, arg-type]
    assert "x" * 40 not in repr(settings)


def test_demo_protection_defaults() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (settings.max_message_chars, settings.daily_message_limit) == (1000, 50)
    assert settings.daily_budget_usd == 1.0


# ------------------------------------------------------------------ request ids
def _echo_app() -> FastAPI:
    app = FastAPI()

    @app.get("/x")
    async def x() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(RequestIdMiddleware)
    return app


def test_request_id_is_generated_echoed_and_hardened() -> None:
    client = TestClient(_echo_app())
    generated = client.get("/x").headers["X-Request-ID"]
    assert len(generated) == 32
    assert (
        client.get("/x", headers={"X-Request-ID": "trace-12345678"}).headers["X-Request-ID"]
        == "trace-12345678"
    )
    for hostile in ("short", "x" * 200, "has space and \t tab", "<script>alert(1)</script>"):
        replaced = client.get("/x", headers={"X-Request-ID": hostile}).headers["X-Request-ID"]
        assert replaced != hostile  # never reflected into logs or responses


def test_security_headers_are_added() -> None:
    headers = TestClient(_echo_app()).get("/x").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"
