"""Daily message counts and the global budget, in Postgres (atomic upserts, UTC days)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.api.limits import UsageStore
from medagent.db.models import Patient, User

pytestmark = pytest.mark.integration


@pytest.fixture
def users(session: Session) -> tuple[int, int]:
    patient_a, patient_b = Patient(name="a"), Patient(name="b")
    session.add_all([patient_a, patient_b])
    session.flush()
    first = User(username="usage-a", password_hash="x", patient_id=patient_a.id)
    second = User(username="usage-b", password_hash="x", patient_id=patient_b.id)
    session.add_all([first, second])
    session.commit()
    return first.id, second.id


@pytest.fixture
def clock() -> dict[str, datetime]:
    return {"now": datetime(2026, 11, 2, 10, 0, tzinfo=UTC)}


@pytest.fixture
def store(engine: Engine, session: Session, clock: dict[str, datetime]) -> UsageStore:
    return UsageStore(sessionmaker(bind=engine, expire_on_commit=False), lambda: clock["now"])


def test_counts_messages_and_cost_per_user_and_sums_globally(
    store: UsageStore, users: tuple[int, int]
) -> None:
    a, b = users
    store.start_message(a)
    store.start_message(a)
    store.start_message(b)
    store.add_cost(a, 0.0123)
    store.add_cost(b, 0.0077)
    assert (store.messages_today(a), store.messages_today(b)) == (2, 1)
    assert store.global_spend_today() == Decimal("0.020000")


def test_a_new_utc_day_starts_from_zero(
    store: UsageStore, users: tuple[int, int], clock: dict[str, datetime]
) -> None:
    a, _ = users
    store.start_message(a)
    store.add_cost(a, 0.9)
    clock["now"] = datetime(2026, 11, 3, 0, 0, 1, tzinfo=UTC)  # just past midnight UTC
    assert store.messages_today(a) == 0
    assert store.global_spend_today() == Decimal(0)
    assert store.check(a, message_limit=1, budget_usd=1.0).ok
    clock["now"] = datetime(2026, 11, 2, 23, 59, 59, tzinfo=UTC)  # and yesterday is still counted
    assert store.messages_today(a) == 1


def test_check_reports_why_and_when_to_come_back(
    store: UsageStore, users: tuple[int, int], clock: dict[str, datetime]
) -> None:
    a, b = users
    assert store.check(a, message_limit=2, budget_usd=1.0).ok

    store.start_message(a)
    store.start_message(a)
    capped = store.check(a, message_limit=2, budget_usd=1.0)
    assert (capped.ok, capped.reason) == (False, "daily_messages")
    assert capped.retry_after_seconds == 14 * 3600  # 10:00 UTC -> next midnight
    assert store.check(b, message_limit=2, budget_usd=1.0).ok  # someone else is fine

    store.add_cost(b, 1.0)  # the whole budget, spent by b
    budget = store.check(a, message_limit=2, budget_usd=1.0)
    assert (budget.ok, budget.reason) == (False, "daily_budget")  # budget is reported first
    assert not store.check(b, message_limit=99, budget_usd=1.0).ok  # even for a fresh user


def test_concurrent_increments_are_not_lost(store: UsageStore, users: tuple[int, int]) -> None:
    a, _ = users
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.start_message(a), range(40)))
        list(pool.map(lambda _: store.add_cost(a, 0.001), range(40)))
    assert store.messages_today(a) == 40
    assert store.global_spend_today() == Decimal("0.040000")


def test_user_row_is_removed_with_its_usage(
    store: UsageStore, users: tuple[int, int], session: Session
) -> None:
    a, _ = users
    store.start_message(a)
    session.execute(User.__table__.delete().where(User.id == a))
    session.commit()
    assert store.messages_today(a) == 0  # ON DELETE CASCADE: no orphaned usage rows
    assert session.scalars(select(User.id)).all() == [users[1]]
