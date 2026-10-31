from __future__ import annotations

from datetime import time

from sqlalchemy import CheckConstraint, ForeignKey, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from medagent.db.base import Base
from medagent.db.models.doctor import Doctor


class DoctorSchedule(Base):
    """One working block of a doctor on a weekday, in *clinic-local* wall-clock time.

    Several rows per weekday are allowed (e.g. 08:00-12:00 and 13:00-17:00 for a lunch break).
    """

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
        UniqueConstraint("doctor_id", "weekday", "start_time", name="uq_doctor_schedules_block"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int]  # 0 = Monday ... 6 = Sunday (same as datetime.weekday())
    start_time: Mapped[time] = mapped_column(Time)  # naive on purpose: local wall-clock time
    end_time: Mapped[time] = mapped_column(Time)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")
