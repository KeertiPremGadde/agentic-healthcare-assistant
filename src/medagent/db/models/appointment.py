from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from medagent.db.base import Base


class AppointmentStatus(enum.StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # One *active* booking per doctor and start time. Partial, so a cancelled
        # appointment frees the slot again. The database, not app code, prevents double booking.
        Index(
            "uq_appointments_doctor_start_booked",
            "doctor_id",
            "start_time",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # always UTC
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            native_enum=False,
            create_constraint=True,  # CHECK (status IN (...)) so bad values can't sneak in
            name="status",
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=AppointmentStatus.BOOKED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow, onupdate=_utcnow
    )
