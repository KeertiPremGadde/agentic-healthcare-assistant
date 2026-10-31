"""Limits that protect a public demo that spends real money.

1. `RateLimiter`: sliding window per key (IP or user), in memory. Fine for one server process;
   several instances would each count separately (Phase 8: move to Redis).
2. `UsageStore`: per-user daily message cap and the GLOBAL daily budget, kept in Postgres so
   they survive restarts and are shared by every request. Day = UTC day.

The budget check can overshoot by what concurrent in-flight turns cost (a few tenths of a cent
each); it is a tripwire against runaway spend, not an accounting ledger. The invoice is the
source of truth.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from medagent.db.models import DailyUsage


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, seconds_until_the_oldest_hit_expires)."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False, window_seconds - (now - hits[0])
        hits.append(now)
        return True, 0.0


class ConversationLocks:
    """At most one running turn per conversation (two at once would interleave one booking
    flow). In memory: one server process; several instances need a Postgres advisory lock.

    A lock older than `max_age_seconds` is treated as stale and can be taken again: it is a
    backstop for the rare case where a stream is abandoned before its cleanup could run (the
    longest legitimate turn, a cold OpenStreetMap lookup, takes about a minute)."""

    def __init__(
        self, max_age_seconds: float = 300, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._held: dict[str, float] = {}
        self._max_age = max_age_seconds
        self._clock = clock

    def try_acquire(self, key: str) -> bool:
        now = self._clock()
        taken_at = self._held.get(key)
        if taken_at is not None and now - taken_at < self._max_age:
            return False
        self._held[key] = now
        return True

    def release(self, key: str) -> None:
        self._held.pop(key, None)


@dataclass(frozen=True)
class Allowance:
    ok: bool
    reason: str | None = None  # "daily_messages" | "daily_budget"
    retry_after_seconds: int = 0


def seconds_until_next_utc_day(now: datetime) -> int:
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(1, int((tomorrow - now).total_seconds()))


class UsageStore:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def _today(self) -> date:
        return self._clock().date()

    def global_spend_today(self) -> Decimal:
        with self._session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(DailyUsage.cost_usd), 0)).where(
                    DailyUsage.day == self._today()
                )
            )
        return Decimal(total or 0)

    def messages_today(self, user_id: int) -> int:
        with self._session_factory() as session:
            return (
                session.scalar(
                    select(DailyUsage.messages).where(
                        DailyUsage.day == self._today(), DailyUsage.user_id == user_id
                    )
                )
                or 0
            )

    def check(self, user_id: int, message_limit: int, budget_usd: float) -> Allowance:
        """May this user start an LLM turn now? Checked BEFORE any LLM call."""
        wait = seconds_until_next_utc_day(self._clock())
        if self.global_spend_today() >= Decimal(str(budget_usd)):
            return Allowance(False, "daily_budget", wait)
        if self.messages_today(user_id) >= message_limit:
            return Allowance(False, "daily_messages", wait)
        return Allowance(True)

    def start_message(self, user_id: int) -> None:
        """Count the message up front (atomic upsert), so failed turns count too."""
        self._upsert(user_id, messages=1, cost=Decimal(0))

    def add_cost(self, user_id: int, usd: float) -> None:
        self._upsert(user_id, messages=0, cost=Decimal(str(usd)))

    def _upsert(self, user_id: int, messages: int, cost: Decimal) -> None:
        stmt = insert(DailyUsage).values(
            day=self._today(), user_id=user_id, messages=messages, cost_usd=cost
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[DailyUsage.day, DailyUsage.user_id],
            set_={
                "messages": DailyUsage.messages + stmt.excluded.messages,
                "cost_usd": DailyUsage.cost_usd + stmt.excluded.cost_usd,
            },
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()
