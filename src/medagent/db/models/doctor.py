from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from medagent.db.base import Base

if TYPE_CHECKING:
    from medagent.db.models.doctor_schedule import DoctorSchedule


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(60), index=True)
    city: Mapped[str] = mapped_column(String(80), index=True, server_default="Berlin")
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), server_default=text("'{German,English}'")
    )

    schedules: Mapped[list[DoctorSchedule]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
