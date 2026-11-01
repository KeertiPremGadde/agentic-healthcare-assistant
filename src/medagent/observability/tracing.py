"""Langfuse tracing of every graph run (ADR 0012).

One trace per turn (a user message or the answer to a confirmation). Its nodes, LLM calls and tool
calls show up as nested observations with latency and token usage. A conversation is a Langfuse
*session*, the user is a hashed id, and the route, the kind of reply and the estimated cost are
attached as scores. Nothing is sent when no keys are configured (`NullTracer`).

Privacy (a hard rule of this project: no PII in logs or traces): by default the *content* of
every observation is redacted before it leaves the process (`redact`, below). Structure, timings,
token counts and the route survive; message text, retrieved passages, doctor and patient details,
thread ids and any other string do not. `LANGFUSE_CAPTURE_CONTENT=true` switches that off and is
meant for local development and for eval runs over synthetic questions only.

Tracing must never break a turn: every call into the SDK is guarded, and a failure only logs the
error type.
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

from medagent.core.config import Settings

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler

log = logging.getLogger(__name__)

# Keys whose values describe the *shape* of a run and never its content. Everything else is
# redacted. Add a key here only if its value can never hold user, patient or medical text.
SAFE_KEYS = frozenset(
    {
        "type",
        "role",
        "route",
        "kind",
        "model",
        "model_name",
        "finish_reason",
        "stop_reason",
        "draft_kind",
        "langgraph_node",
        "langgraph_step",
        "langgraph_path",
        "ls_provider",
        "ls_model_name",
        "ls_model_type",
        "ls_max_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read",
        "cache_creation",
        "reasoning",
        "is_emergency",
        "is_harmful",
        "is_self_harm",
        "context_sufficient",
    }
)


def redact(data: Any, _keep: bool = False) -> Any:
    """Replace every string and number that is not under a SAFE key; keep the structure.

    Booleans and None carry no content (flags like `is_emergency`) and are kept. Unknown types are
    replaced outright. The result is always JSON-serialisable.
    """
    if isinstance(data, Mapping):
        return {str(key): redact(value, str(key) in SAFE_KEYS) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [redact(value, _keep) for value in data]
    if data is None or isinstance(data, bool):
        return data
    if isinstance(data, int | float):
        return data if _keep else "[redacted]"
    if isinstance(data, str):
        if _keep or data.startswith("[redacted"):  # idempotent: the two layers don't stack
            return data
        return f"[redacted: {len(data)} chars]"
    return "[redacted]"


def mask(*, data: Any, **_: Any) -> Any:
    """Langfuse's `mask` hook. If this ever raised, the SDK would replace the data entirely."""
    return redact(data)


# ---- Second line of defence: the export-stage hook ----------------------------------------------
# `mask` only sees the input, output and metadata the SDK is given. The LangChain handler also
# stores the text of an *exception* as the observation's status message, and LangGraph's pause for
# a confirmation is an exception whose text holds the proposal (doctor, time, question). So just
# before export every content-bearing attribute is scrubbed again, whatever put it there.
_CONTENT_PREFIXES = (
    "langfuse.observation.input",
    "langfuse.observation.output",
    "langfuse.observation.metadata",
    "langfuse.trace.input",
    "langfuse.trace.output",
    "langfuse.trace.metadata",
)
_STATUS_KEY = "langfuse.observation.status_message"
_EXCEPTION_NAME = re.compile(r"\s*([A-Za-z_][\w.]*(?:Error|Exception|Interrupt))(?!\w)")


def _scrub_status(message: str) -> str:
    if "[redacted" in message:
        return message
    named = _EXCEPTION_NAME.match(message)  # an exception class name holds no content
    prefix = f"{named.group(1)}: " if named else ""
    return f"{prefix}[redacted: {len(message)} chars]"


def _scrub_json(key: str, value: str) -> str:
    """Attributes hold JSON-encoded values; a `.metadata.<name>` key carries its name in the key."""
    keep = False
    for prefix in _CONTENT_PREFIXES:
        if key.startswith(prefix + "."):
            keep = key.rsplit(".", 1)[-1] in SAFE_KEYS
    try:
        decoded = json.loads(value)
    except ValueError:
        return str(redact(value, keep))  # a raw string
    return json.dumps(redact(decoded, keep), ensure_ascii=False)


def scrub_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """The attribute changes that remove content from one exported span (pure)."""
    changes: dict[str, Any] = {}
    for key, value in attributes.items():
        if not isinstance(value, str):
            continue
        if key == _STATUS_KEY:
            new = _scrub_status(value)
        elif key.startswith(_CONTENT_PREFIXES):
            new = _scrub_json(key, value)
        else:
            continue
        if new != value:
            changes[key] = new
    return changes


def mask_otel_spans(*, params: Any) -> Any:
    """Langfuse's export-stage hook. If it raised, the SDK would drop the whole batch, so a span it
    cannot scrub gets its content attributes deleted instead."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches: dict[Any, Any] = {}
    for identifier, span in params.spans.items():
        try:
            changes = scrub_attributes(span.attributes)
            if changes:
                patches[identifier] = OtelSpanPatch(set_attributes=changes)
        except Exception:
            drop = tuple(
                k for k in span.attributes if k.startswith(_CONTENT_PREFIXES) or k == _STATUS_KEY
            )
            patches[identifier] = OtelSpanPatch(delete_attributes=drop)
    return MaskOtelSpansResult(span_patches=patches) if patches else None


@dataclass(frozen=True, slots=True)
class TraceContext:
    """What the caller knows about a turn. `user_id` must already be pseudonymised."""

    session_id: str | None = None  # the conversation id (random, carries no user information)
    user_id: str | None = None
    tags: tuple[str, ...] = ()


class TurnTrace(Protocol):
    callbacks: list[BaseCallbackHandler]
    metadata: dict[str, Any]

    def finish(
        self,
        *,
        route: str,
        kind: str,
        usd: float,
        input_tokens: int,
        output_tokens: int,
        paused: bool,
    ) -> None: ...


class Tracer(Protocol):
    def start(self, context: TraceContext | None, *, kind: str) -> TurnTrace: ...

    def shutdown(self) -> None: ...


@dataclass
class _NullTrace:
    callbacks: list[BaseCallbackHandler] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(self, **_: Any) -> None:
        return None


class NullTracer:
    """Tracing off: no callbacks, nothing sent."""

    def start(self, context: TraceContext | None, *, kind: str) -> TurnTrace:
        return _NullTrace()

    def shutdown(self) -> None:
        return None


class _LangfuseClient(Protocol):
    def create_trace_id(self) -> str: ...

    def create_score(self, **kwargs: Any) -> None: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


@dataclass
class _LangfuseTrace:
    callbacks: list[BaseCallbackHandler]
    metadata: dict[str, Any]
    trace_id: str
    client: _LangfuseClient

    def finish(
        self,
        *,
        route: str,
        kind: str,
        usd: float,
        input_tokens: int,
        output_tokens: int,
        paused: bool,
    ) -> None:
        # Scores make the trace filterable in the UI (by route, kind, cost) without any content.
        scores: list[dict[str, Any]] = [
            {"name": "route", "value": route or "unknown", "data_type": "CATEGORICAL"},
            {"name": "kind", "value": kind, "data_type": "CATEGORICAL"},
            {"name": "est_cost_usd", "value": float(usd), "data_type": "NUMERIC"},
        ]
        for score in scores:
            try:
                self.client.create_score(trace_id=self.trace_id, **score)
            except Exception as exc:
                log.warning("tracing_score_failed", extra={"error": type(exc).__name__})
                return


class LangfuseTracer:
    def __init__(
        self,
        client: _LangfuseClient,
        handler_factory: Callable[[str], BaseCallbackHandler],
        *,
        environment: str = "local",
        sample_rate: float = 1.0,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._handler_factory = handler_factory
        self._environment = environment
        self._sample_rate = sample_rate
        self._rng = rng

    def start(self, context: TraceContext | None, *, kind: str) -> TurnTrace:
        # Sampling is decided here, once per turn, so a skipped turn sends no scores either.
        if self._sample_rate < 1.0 and self._rng() >= self._sample_rate:
            return _NullTrace()
        try:
            trace_id = self._client.create_trace_id()
            handler = self._handler_factory(trace_id)
        except Exception as exc:
            log.warning("tracing_start_failed", extra={"error": type(exc).__name__})
            return _NullTrace()
        context = context or TraceContext()
        # Keys the Langfuse callback handler reads from the run's metadata.
        metadata: dict[str, Any] = {"langfuse_tags": [*context.tags, kind, self._environment]}
        if context.session_id:
            metadata["langfuse_session_id"] = context.session_id
        if context.user_id:
            metadata["langfuse_user_id"] = context.user_id
        return _LangfuseTrace([handler], metadata, trace_id, self._client)

    def shutdown(self) -> None:
        try:
            self._client.flush()
            self._client.shutdown()
        except Exception as exc:
            log.warning("tracing_shutdown_failed", extra={"error": type(exc).__name__})


def get_tracer(settings: Settings) -> Tracer:
    """Langfuse when both keys are set (and not switched off), otherwise a no-op."""
    key = settings.langfuse_secret_key
    if not settings.langfuse_enabled or not settings.langfuse_public_key or key is None:
        return NullTracer()
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler
    from langfuse.span_filter import is_langfuse_span

    public_key = settings.langfuse_public_key
    client = Langfuse(
        public_key=public_key,
        secret_key=key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
        # Redact by default; our own sampling in LangfuseTracer.start keeps scores consistent.
        mask=None if settings.langfuse_capture_content else mask,
        mask_otel_spans=None if settings.langfuse_capture_content else mask_otel_spans,
        # Export only spans the Langfuse SDK itself created. The Anthropic SDK also emits its own
        # span for every call: a duplicate of the LangChain generation (extra units) and a second
        # path into the trace that the redaction hooks were not written for.
        should_export_span=is_langfuse_span,
    )
    return LangfuseTracer(
        cast(_LangfuseClient, client),  # the SDK's overloaded create_score fits our narrower use
        lambda trace_id: CallbackHandler(
            public_key=public_key, trace_context={"trace_id": trace_id}
        ),
        environment=settings.app_env,
        sample_rate=settings.langfuse_sample_rate,
    )
