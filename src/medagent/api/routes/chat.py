"""Chat: send a message (SSE or JSON), answer a pending confirmation, read the history.

Conversation ids are namespaced by user (`u{user_id}:{conversation_id}`) before they reach the
graph, so a user can never read, resume or write another user's conversation: an id that isn't
theirs simply doesn't exist for them (404). The patient being booked comes from the token.

Cost protection runs BEFORE any LLM call: per-user rate, per-user daily messages, and the
global daily budget. When a limit is hit, red-flag rules still run, so an emergency message
gets the emergency answer (no LLM involved) instead of a "limit reached" error.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from medagent.agents.runner import FinalEvent, StepEvent, TurnResult, stream_turn, turn_config
from medagent.api.deps import CurrentUser, CurrentUserDep, ResourcesDep, enforce_rate_limit
from medagent.api.errors import DEMO_NOTICE, ApiError
from medagent.api.resources import Resources
from medagent.api.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HistoryResponse,
    LimitsOut,
    MessageOut,
    ResumeRequest,
    UsageOut,
)
from medagent.api.sse import KEEPALIVE_SECONDS, STEP_LABELS, chunk_text, keepalive, sse
from medagent.guardrails.emergency import EMERGENCY_MESSAGE, detect_red_flag
from medagent.observability.cost import RunCost

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])

_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "`text/event-stream` with events `step`, `token`, `confirmation`, "
        "`message`, `done` and `error`; or JSON (`ChatResponse`) with `?stream=false`.",
        "content": {"text/event-stream": {}},
    },
    409: {
        "model": ErrorResponse,
        "description": "A turn is already running, or nothing to confirm.",
    },
    429: {"model": ErrorResponse, "description": "Rate limit or daily limit reached."},
    503: {"model": ErrorResponse, "description": "The demo's daily budget is used up."},
}

LIMIT_MESSAGES = {
    "daily_messages": "You've reached today's message limit for this demo. Come back tomorrow.",
    "daily_budget": "The demo limit for today has been reached. Please come back tomorrow.",
}


def thread_id_for(user: CurrentUser, conversation_id: str) -> str:
    return f"u{user.id}:{conversation_id}"


def _usage(cost: RunCost) -> UsageOut:
    return UsageOut(
        input_tokens=cost.input_tokens, output_tokens=cost.output_tokens, est_cost_usd=cost.usd
    )


def _acquire(res: Resources, thread_id: str) -> None:
    if not res.locks.try_acquire(thread_id):
        raise ApiError(
            409, "conversation_busy", "This conversation is still working on your last message."
        )


async def _stream(
    res: Resources,
    user: CurrentUser,
    thread_id: str,
    conversation_id: str,
    *,
    message: str | None = None,
    resume: object = None,
) -> AsyncIterator[bytes]:
    """Run the turn in a task and relay its events; send keepalives while it works.

    The lock is released when the stream ends or the client disconnects (the task is then
    cancelled; the database write inside a tool call is atomic, so a cancel can't half-book)."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    delay = res.settings.token_replay_delay_ms / 1000

    def record(cost: RunCost) -> None:
        if cost.usd:
            res.usage.add_cost(user.id, cost.usd)

    async def produce() -> None:
        try:
            async for event in stream_turn(
                res.graph,
                thread_id,
                user.patient_id,
                message=message,
                resume=resume,
                on_cost=record,
            ):
                if isinstance(event, StepEvent):
                    if label := STEP_LABELS.get(event.node):
                        await queue.put(sse("step", {"node": event.node, "label": label}))
                elif isinstance(event, FinalEvent):
                    await _emit_final(queue, event.result, conversation_id, delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("chat_stream_failed", extra={"error": type(exc).__name__})  # type only
            await queue.put(
                sse(
                    "error",
                    {"code": "internal_error", "message": "Something went wrong on our side."},
                )
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                yield keepalive()
                continue
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        res.locks.release(thread_id)


async def _emit_final(
    queue: asyncio.Queue[bytes | None], result: TurnResult, conversation_id: str, delay: float
) -> None:
    if result.pending is not None:
        await queue.put(sse("confirmation", result.pending))
    elif result.reply is not None:
        for chunk in chunk_text(result.reply):
            await queue.put(sse("token", {"text": chunk}))
            if delay:
                await asyncio.sleep(delay)
        await queue.put(sse("message", {"text": result.reply}))
    await queue.put(
        sse(
            "done",
            {
                "conversation_id": conversation_id,
                "pending": result.pending is not None,
                "usage": _usage(result.cost).model_dump(),
            },
        )
    )


async def _respond(
    res: Resources,
    user: CurrentUser,
    thread_id: str,
    conversation_id: str,
    stream: bool,
    *,
    message: str | None = None,
    resume: object = None,
) -> StreamingResponse | ChatResponse:
    """Stream (SSE) or run to completion (JSON). Takes over the lock for the turn."""
    if stream:
        generator = _stream(res, user, thread_id, conversation_id, message=message, resume=resume)
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    try:
        result: TurnResult | None = None
        async for event in stream_turn(
            res.graph,
            thread_id,
            user.patient_id,
            message=message,
            resume=resume,
            on_cost=lambda cost: res.usage.add_cost(user.id, cost.usd) if cost.usd else None,
        ):
            if isinstance(event, FinalEvent):
                result = event.result
    finally:
        res.locks.release(thread_id)
    assert result is not None
    return ChatResponse(
        conversation_id=conversation_id,
        reply=result.reply,
        pending=result.pending,
        usage=_usage(result.cost),
    )


async def _limit_response(
    res: Resources, conversation_id: str, stream: bool, reply: str
) -> StreamingResponse | ChatResponse:
    """A fixed answer with no LLM call (used for emergencies when a limit is reached)."""
    zero = RunCost(0, 0, 0, 0.0)
    if not stream:
        return ChatResponse(
            conversation_id=conversation_id, reply=reply, pending=None, usage=_usage(zero)
        )

    async def one_shot() -> AsyncIterator[bytes]:
        yield sse("message", {"text": reply})
        yield sse(
            "done",
            {
                "conversation_id": conversation_id,
                "pending": False,
                "usage": _usage(zero).model_dump(),
            },
        )

    return StreamingResponse(one_shot(), media_type="text/event-stream")


@router.post(
    "/chat",
    summary="Send a message",
    description="Streams events (`step`, `token`, `confirmation`, `message`, `done`) over SSE. "
    "Use `?stream=false` for one JSON response (handy in /docs). If the assistant needs a "
    "yes/no (booking or cancelling), the response carries `pending`; answer it with "
    "`POST /v1/chat/{conversation_id}/resume`. " + DEMO_NOTICE,
    response_model=ChatResponse,
    responses=_STREAM_RESPONSES,
)
async def chat(
    body: ChatRequest,
    user: CurrentUserDep,
    res: ResourcesDep,
    stream: bool = Query(default=True, description="false = a single JSON response"),
) -> StreamingResponse | ChatResponse:
    settings = res.settings
    enforce_rate_limit(res, f"chat:{user.id}", settings.chat_rate_per_minute, 60)
    if len(body.message) > settings.max_message_chars:
        raise ApiError(
            422,
            "message_too_long",
            f"Please keep messages under {settings.max_message_chars} characters.",
        )
    conversation_id = body.conversation_id or uuid.uuid4().hex
    thread_id = thread_id_for(user, conversation_id)

    allowance = await asyncio.to_thread(
        res.usage.check, user.id, settings.daily_message_limit, settings.daily_budget_usd
    )
    if not allowance.ok:
        flag = detect_red_flag(body.message)
        if flag is not None and not flag.informational:
            # Safety first: the deterministic rules need no LLM, so they still answer.
            return await _limit_response(res, conversation_id, stream, EMERGENCY_MESSAGE)
        status = 503 if allowance.reason == "daily_budget" else 429
        raise ApiError(
            status,
            "demo_limit_reached",
            LIMIT_MESSAGES[allowance.reason or "daily_budget"],
            {"Retry-After": str(allowance.retry_after_seconds)},
        )

    _acquire(res, thread_id)
    try:
        await asyncio.to_thread(res.usage.start_message, user.id)
    except BaseException:
        res.locks.release(thread_id)
        raise
    return await _respond(res, user, thread_id, conversation_id, stream, message=body.message)


@router.post(
    "/chat/{conversation_id}/resume",
    summary="Answer a pending confirmation",
    description="Resume a conversation that is waiting for your yes/no (a booking or a "
    "cancellation). Costs nothing: no language-model call is involved, so it also works when "
    "the daily limits are reached.",
    response_model=ChatResponse,
    responses=_STREAM_RESPONSES | {404: {"model": ErrorResponse}},
)
async def resume(
    conversation_id: str,
    body: ResumeRequest,
    user: CurrentUserDep,
    res: ResourcesDep,
    stream: bool = Query(default=True, description="false = a single JSON response"),
) -> StreamingResponse | ChatResponse:
    enforce_rate_limit(res, f"chat:{user.id}", res.settings.chat_rate_per_minute, 60)
    thread_id = thread_id_for(user, _valid_conversation_id(conversation_id))
    _acquire(res, thread_id)
    try:
        snapshot = await res.graph.aget_state(turn_config(thread_id, user.patient_id))
        if not snapshot.values:
            raise ApiError(404, "not_found", "Conversation not found.")
        if not snapshot.interrupts:
            raise ApiError(
                409, "nothing_to_confirm", "This conversation isn't waiting for an answer."
            )
    except BaseException:
        res.locks.release(thread_id)
        raise
    return await _respond(res, user, thread_id, conversation_id, stream, resume=body.confirmed)


@router.get(
    "/chat/{conversation_id}",
    summary="Conversation history and any pending confirmation",
    response_model=HistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
async def history(conversation_id: str, user: CurrentUserDep, res: ResourcesDep) -> HistoryResponse:
    thread_id = thread_id_for(user, _valid_conversation_id(conversation_id))
    snapshot = await res.graph.aget_state(turn_config(thread_id, user.patient_id))
    if not snapshot.values:
        raise ApiError(404, "not_found", "Conversation not found.")
    messages = [
        MessageOut(
            role="user" if isinstance(m, HumanMessage) else "assistant", content=str(m.content)
        )
        for m in snapshot.values.get("messages", [])
        if isinstance(m, HumanMessage | AIMessage)
    ]
    pending = snapshot.interrupts[0].value if snapshot.interrupts else None
    return HistoryResponse(conversation_id=conversation_id, messages=messages, pending=pending)


@router.get(
    "/limits",
    summary="The demo's limits and how much of today's allowance you've used",
    response_model=LimitsOut,
)
async def limits(user: CurrentUserDep, res: ResourcesDep) -> LimitsOut:
    used = await asyncio.to_thread(res.usage.messages_today, user.id)
    return LimitsOut(
        max_message_chars=res.settings.max_message_chars,
        daily_message_limit=res.settings.daily_message_limit,
        messages_used_today=used,
        demo_notice=DEMO_NOTICE,
    )


def _valid_conversation_id(conversation_id: str) -> str:
    if len(conversation_id) != 32 or any(c not in "0123456789abcdef" for c in conversation_id):
        raise ApiError(
            404, "not_found", "Conversation not found."
        )  # not an id we could have issued
    return conversation_id
