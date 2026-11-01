"""Tracing: redaction (the privacy guarantee), tracer behaviour, failure isolation. No network."""

import json
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import SecretStr

from medagent.core.config import Settings
from medagent.observability import tracing
from medagent.observability.tracing import (
    LangfuseTracer,
    NullTracer,
    TraceContext,
    get_tracer,
    mask,
    redact,
)

# ------------------------------------------------------------------ redaction


def test_text_is_replaced_by_its_length_and_the_structure_stays() -> None:
    data = {"messages": [{"type": "human", "content": "I have chest pain and take metformin"}]}
    out = redact(data)
    assert out == {"messages": [{"type": "human", "content": "[redacted: 36 chars]"}]}


def test_shape_keys_survive_and_everything_else_does_not() -> None:
    data = {
        "route": "book",
        "is_emergency": False,
        "langgraph_node": "supervisor",
        "langgraph_step": 3,
        "thread_id": "u42:0123456789abcdef0123456789abcdef",
        "patient_id": 7,
        "draft": "Dr. Anna Schmidt has a free slot",
        "specialty": "Cardiologist",
    }
    out = redact(data)
    assert out["route"] == "book"
    assert out["is_emergency"] is False
    assert out["langgraph_node"] == "supervisor"
    assert out["langgraph_step"] == 3
    # identifiers and anything about the person or the condition are gone
    assert out["thread_id"].startswith("[redacted")
    assert out["patient_id"] == "[redacted]"
    assert out["draft"].startswith("[redacted")
    assert out["specialty"].startswith("[redacted")  # a specialty reveals the symptoms


def test_token_counts_are_kept_under_their_keys() -> None:
    out = redact({"usage_metadata": {"input_tokens": 120, "output_tokens": 9, "total_tokens": 129}})
    assert out == {"usage_metadata": {"input_tokens": 120, "output_tokens": 9, "total_tokens": 129}}


def test_lists_and_nested_values_are_walked() -> None:
    out = redact({"doctor_options": [{"name": "Dr. A", "languages": ["German"], "id": 4}]})
    flat = json.dumps(out)
    assert "Dr. A" not in flat
    assert "German" not in flat
    assert out["doctor_options"][0]["id"] == "[redacted]"


@pytest.mark.parametrize(
    "secret",
    ["metformin", "Dr. Anna Schmidt", "u42:abc", "alex.example@example.com", "0800 111 0 111"],
)
def test_no_leaf_text_survives_in_a_realistic_payload(secret: str) -> None:
    payload = {
        "input": {"messages": [{"type": "human", "content": f"please {secret}"}]},
        "output": {"draft": secret, "proposal": {"doctor_name": secret, "start_local": secret}},
        "metadata": {"thread_id": f"x-{secret}", "patient_id": 3, "email": secret},
    }
    assert secret not in json.dumps(redact(payload))


def test_unknown_types_are_replaced_and_the_result_is_json_serialisable() -> None:
    class Weird:
        def __repr__(self) -> str:
            return "secret-object"

    out = redact({"x": Weird(), "y": (1, "two"), "z": None, "ok": True})
    assert "secret-object" not in json.dumps(out)
    json.dumps(out)
    assert out["z"] is None
    assert out["ok"] is True


def test_the_langfuse_hook_takes_keyword_data_and_ignores_extra_arguments() -> None:
    assert mask(data="hello", level="x") == "[redacted: 5 chars]"


# ------------------------------------------------------------------ tracer behaviour


class FakeClient:
    def __init__(self, *, fail_scores: bool = False, fail_trace_id: bool = False) -> None:
        self.scores: list[dict[str, Any]] = []
        self.flushed = self.shut_down = 0
        self.fail_scores = fail_scores
        self.fail_trace_id = fail_trace_id
        self.next_id = 0

    def create_trace_id(self) -> str:
        if self.fail_trace_id:
            raise RuntimeError("boom")
        self.next_id += 1
        return f"trace-{self.next_id}"

    def create_score(self, **kwargs: Any) -> None:
        if self.fail_scores:
            raise RuntimeError("boom")
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed += 1

    def shutdown(self) -> None:
        self.shut_down += 1


class Recorder(BaseCallbackHandler):
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id


def _tracer(client: FakeClient, **kwargs: Any) -> LangfuseTracer:
    return LangfuseTracer(client, Recorder, **kwargs)


def test_a_turn_gets_a_handler_session_hashed_user_and_tags() -> None:
    trace = _tracer(FakeClient(), environment="staging").start(
        TraceContext(session_id="conv1", user_id="abc123", tags=("api",)), kind="message"
    )
    assert [type(h) for h in trace.callbacks] == [Recorder]
    assert trace.callbacks[0].trace_id == "trace-1"  # type: ignore[attr-defined]
    assert trace.metadata == {
        "langfuse_session_id": "conv1",
        "langfuse_user_id": "abc123",
        "langfuse_tags": ["api", "message", "staging"],
    }


def test_without_a_context_there_is_no_session_or_user() -> None:
    trace = _tracer(FakeClient()).start(None, kind="resume")
    assert set(trace.metadata) == {"langfuse_tags"}
    assert trace.metadata["langfuse_tags"] == ["resume", "local"]


def test_finish_attaches_route_kind_and_cost_as_scores() -> None:
    client = FakeClient()
    trace = _tracer(client).start(TraceContext(session_id="c"), kind="message")
    trace.finish(
        route="book", kind="booked", usd=0.0004, input_tokens=900, output_tokens=40, paused=False
    )
    assert client.scores == [
        {"trace_id": "trace-1", "name": "route", "value": "book", "data_type": "CATEGORICAL"},
        {"trace_id": "trace-1", "name": "kind", "value": "booked", "data_type": "CATEGORICAL"},
        {"trace_id": "trace-1", "name": "est_cost_usd", "value": 0.0004, "data_type": "NUMERIC"},
    ]


def test_an_empty_route_is_reported_as_unknown() -> None:
    client = FakeClient()
    _tracer(client).start(None, kind="message").finish(
        route="", kind="normal", usd=0, input_tokens=0, output_tokens=0, paused=True
    )
    assert client.scores[0]["value"] == "unknown"


def test_a_failing_score_never_raises() -> None:
    trace = _tracer(FakeClient(fail_scores=True)).start(None, kind="message")
    trace.finish(route="x", kind="normal", usd=0, input_tokens=0, output_tokens=0, paused=False)


def test_a_failing_start_degrades_to_no_tracing() -> None:
    trace = _tracer(FakeClient(fail_trace_id=True)).start(None, kind="message")
    assert trace.callbacks == []
    trace.finish(route="x", kind="normal", usd=0, input_tokens=0, output_tokens=0, paused=False)


def test_sampling_skips_whole_turns_including_their_scores() -> None:
    client = FakeClient()
    tracer = _tracer(client, sample_rate=0.25, rng=iter([0.1, 0.9, 0.3]).__next__)
    kept = [tracer.start(None, kind="message") for _ in range(3)]
    assert [bool(t.callbacks) for t in kept] == [True, False, False]
    for trace in kept:
        trace.finish(route="x", kind="normal", usd=0, input_tokens=0, output_tokens=0, paused=False)
    assert {s["trace_id"] for s in client.scores} == {"trace-1"}  # only the traced turn is scored


def test_a_rate_of_zero_traces_nothing_and_one_traces_everything() -> None:
    client = FakeClient()
    assert _tracer(client, sample_rate=0.0).start(None, kind="message").callbacks == []
    assert client.next_id == 0
    assert _tracer(client, sample_rate=1.0).start(None, kind="message").callbacks


def test_shutdown_flushes_and_swallows_errors() -> None:
    client = FakeClient()
    _tracer(client).shutdown()
    assert (client.flushed, client.shut_down) == (1, 1)

    class Broken(FakeClient):
        def flush(self) -> None:
            raise RuntimeError("network down")

    _tracer(Broken()).shutdown()  # no exception


def test_the_null_tracer_does_nothing() -> None:
    trace = NullTracer().start(TraceContext(session_id="c"), kind="message")
    assert trace.callbacks == []
    assert trace.metadata == {}
    trace.finish(route="x", kind="normal", usd=0, input_tokens=0, output_tokens=0, paused=False)
    NullTracer().shutdown()


# ------------------------------------------------------------------ get_tracer


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_no_keys_means_no_tracing() -> None:
    assert isinstance(get_tracer(_settings()), NullTracer)
    only_public = _settings(langfuse_public_key="pk-lf-x")
    assert isinstance(get_tracer(only_public), NullTracer)


def test_keys_can_be_switched_off_without_removing_them() -> None:
    off = _settings(
        langfuse_public_key="pk-lf-x",
        langfuse_secret_key=SecretStr("sk-lf-x"),
        langfuse_enabled=False,
    )
    assert isinstance(get_tracer(off), NullTracer)


@pytest.mark.parametrize(("capture", "expected_mask"), [(False, mask), (True, None)])
def test_content_is_redacted_unless_capture_is_switched_on(
    monkeypatch: pytest.MonkeyPatch, capture: bool, expected_mask: Any
) -> None:
    created: list[dict[str, Any]] = []

    class FakeLangfuse(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            created.append(kwargs)

    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    settings = _settings(
        langfuse_public_key="pk-lf-x",
        langfuse_secret_key=SecretStr("sk-lf-secret"),
        langfuse_base_url="https://cloud.langfuse.com",
        langfuse_capture_content=capture,
        app_env="staging",
        jwt_secret=SecretStr("x" * 40),  # staging refuses the placeholder secret
    )
    tracer = get_tracer(settings)
    assert isinstance(tracer, LangfuseTracer)
    (kwargs,) = created
    assert kwargs["mask"] is expected_mask
    assert kwargs["base_url"] == "https://cloud.langfuse.com"
    assert kwargs["environment"] == "staging"
    assert kwargs["public_key"] == "pk-lf-x"
    assert kwargs["secret_key"] == "sk-lf-secret"


def test_the_secret_key_is_not_in_the_settings_repr() -> None:
    settings = _settings(langfuse_secret_key=SecretStr("sk-lf-secret"))
    assert "sk-lf-secret" not in repr(settings)


def test_every_safe_key_is_a_plain_shape_key() -> None:
    """A guard for future edits: nothing that could hold text may join the allow-list."""
    forbidden = {"content", "text", "message", "messages", "draft", "name", "email", "thread_id"}
    assert not forbidden & tracing.SAFE_KEYS


# ------------------------------------------------------------------ export-stage scrubber


INTERRUPT_TEXT = (
    "GraphInterrupt((Interrupt(value={'type': 'confirm_booking', 'doctor': 'Dr. Olivia Martinez', "
    "'start': 'Mon 2 Nov 2026, 08:30', 'question': 'Shall I book Mon 2 Nov 2026?'})))"
)


def test_the_text_of_a_pause_for_confirmation_is_scrubbed_but_the_exception_name_stays() -> None:
    """Found on the real stack: the LangChain handler stores an exception's text as the status
    message, and LangGraph's pause for a confirmation is an exception holding the proposal."""
    changes = tracing.scrub_attributes({"langfuse.observation.status_message": INTERRUPT_TEXT})
    out = changes["langfuse.observation.status_message"]
    assert out == f"GraphInterrupt: [redacted: {len(INTERRUPT_TEXT)} chars]"
    assert "Olivia" not in out


def test_an_exception_message_that_is_not_a_class_name_is_fully_redacted() -> None:
    out = tracing.scrub_attributes(
        {"langfuse.observation.status_message": "Alex said he has chest pain"}
    )["langfuse.observation.status_message"]
    assert out == "[redacted: 27 chars]"


def test_input_output_and_metadata_attributes_are_scrubbed_inside_their_json() -> None:
    attributes = {
        "langfuse.observation.input": json.dumps(
            {"messages": [{"type": "human", "content": "I take metformin"}]}
        ),
        "langfuse.observation.output": json.dumps({"route": "book", "draft": "Dr. A at 9"}),
        "langfuse.observation.metadata": json.dumps({"thread_id": "u4:abc", "ls_provider": "x"}),
    }
    changes = tracing.scrub_attributes(attributes)
    assert json.loads(changes["langfuse.observation.input"]) == {
        "messages": [{"type": "human", "content": "[redacted: 16 chars]"}]
    }
    assert json.loads(changes["langfuse.observation.output"]) == {
        "route": "book",
        "draft": "[redacted: 10 chars]",
    }
    assert json.loads(changes["langfuse.observation.metadata"]) == {
        "thread_id": "[redacted: 6 chars]",
        "ls_provider": "x",
    }


def test_per_key_metadata_attributes_use_the_name_in_the_key() -> None:
    changes = tracing.scrub_attributes(
        {
            "langfuse.observation.metadata.langgraph_node": json.dumps("supervisor"),
            "langfuse.observation.metadata.thread_id": json.dumps("u4:abc"),
        }
    )
    assert "langfuse.observation.metadata.langgraph_node" not in changes  # shape: kept
    assert json.loads(changes["langfuse.observation.metadata.thread_id"]).startswith("[redacted")


def test_other_attributes_are_left_alone() -> None:
    attributes = {
        "langfuse.observation.type": "span",
        "langfuse.observation.model.name": "claude-haiku-5-5",
        "langfuse.observation.usage_details": json.dumps({"input": 5}),
        "session.id": "conv",
        "user.id": "abc123",
        "langfuse.trace.tags": ["api"],
    }
    assert tracing.scrub_attributes(attributes) == {}


def test_scrubbing_twice_changes_nothing_more() -> None:
    attributes = {
        "langfuse.observation.input": json.dumps({"content": "hello there"}),
        "langfuse.observation.status_message": INTERRUPT_TEXT,
    }
    once = {**attributes, **tracing.scrub_attributes(attributes)}
    assert tracing.scrub_attributes(once) == {}


def test_the_export_hook_patches_only_spans_with_content() -> None:
    from types import SimpleNamespace

    dirty = SimpleNamespace(attributes={"langfuse.observation.status_message": INTERRUPT_TEXT})
    clean = SimpleNamespace(attributes={"langfuse.observation.type": "span"})
    result = tracing.mask_otel_spans(params=SimpleNamespace(spans={"a": dirty, "b": clean}))
    assert set(result.span_patches) == {"a"}
    assert "Olivia" not in json.dumps(dict(result.span_patches["a"].set_attributes))
    assert tracing.mask_otel_spans(params=SimpleNamespace(spans={"b": clean})) is None


def test_a_span_that_cannot_be_scrubbed_loses_its_content_attributes_instead_of_the_batch() -> None:
    from types import SimpleNamespace

    class Exploding(dict):  # type: ignore[type-arg]
        def items(self) -> Any:
            raise RuntimeError("boom")

        def __iter__(self) -> Any:
            return iter(["langfuse.observation.input", "langfuse.observation.type"])

    span = SimpleNamespace(attributes=Exploding())
    result = tracing.mask_otel_spans(params=SimpleNamespace(spans={"x": span}))
    assert tuple(result.span_patches["x"].delete_attributes) == ("langfuse.observation.input",)


def test_the_export_hook_is_installed_unless_content_capture_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []

    class FakeLangfuse(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            created.append(kwargs)

    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    for capture in (False, True):
        get_tracer(
            _settings(
                langfuse_public_key="pk-lf-x",
                langfuse_secret_key=SecretStr("sk-lf-x"),
                langfuse_capture_content=capture,
            )
        )
    assert created[0]["mask_otel_spans"] is tracing.mask_otel_spans
    assert created[1]["mask_otel_spans"] is None


def test_only_spans_created_by_the_langfuse_sdk_are_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Anthropic SDK emits its own span per call: a duplicate and an unredacted path."""
    from langfuse.span_filter import is_langfuse_span

    created: list[dict[str, Any]] = []

    class FakeLangfuse(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            created.append(kwargs)

    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    get_tracer(_settings(langfuse_public_key="pk-lf-x", langfuse_secret_key=SecretStr("sk-lf-x")))
    assert created[0]["should_export_span"] is is_langfuse_span
