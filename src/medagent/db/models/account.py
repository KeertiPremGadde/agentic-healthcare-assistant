from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from medagent.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """A demo account. Username + password only: no email or other personal data is collected.
    Each user owns one synthetic patient record, and that link is how the API knows who is
    booking (never the chat text)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))  # Argon2id, never the password
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )


class DailyUsage(Base):
    """Chat messages and estimated LLM spend per user per UTC day. Sums over a day give the
    global spend that the demo budget is checked against."""

    __tablename__ = "daily_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    messages: Mapped[int] = mapped_column(default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal(0), server_default="0"
    )
