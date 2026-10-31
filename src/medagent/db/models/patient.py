from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from medagent.db.base import Base


class Patient(Base):
    """Synthetic patients only; never store real personal data."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int | None]
    gender: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(40), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
