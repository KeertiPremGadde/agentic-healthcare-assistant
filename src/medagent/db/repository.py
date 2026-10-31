"""Thin DB access used by tools and the API. Domain rules live in `services/`."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medagent.db.models import Appointment, AppointmentStatus, Doctor, DoctorSchedule
from medagent.services.availability import WorkingWindow, clinic_day_bounds


class SlotTakenError(Exception):
    """Raised when the unique index rejects a double booking."""


def get_doctors(session: Session, specialty: str | None = None) -> list[Doctor]:
    stmt = select(Doctor).order_by(Doctor.id)
    if specialty:
        stmt = stmt.where(Doctor.specialty == specialty)
    return list(session.scalars(stmt))


def get_working_windows(session: Session, doctor_id: int) -> list[WorkingWindow]:
    rows = session.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
    return [WorkingWindow(r.weekday, r.start_time, r.end_time) for r in rows]


def get_booked_starts(session: Session, doctor_id: int, day: date, tz: ZoneInfo) -> list[datetime]:
    lo, hi = clinic_day_bounds(day, tz)
    stmt = select(Appointment.start_time).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.start_time >= lo,
        Appointment.start_time < hi,
    )
    return list(session.scalars(stmt))


def create_appointment(
    session: Session, patient_id: int, doctor_id: int, start_time: datetime
) -> Appointment:
    """Insert and commit; translate the unique-index violation into SlotTakenError."""
    appointment = Appointment(patient_id=patient_id, doctor_id=doctor_id, start_time=start_time)
    session.add(appointment)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if "uq_appointments_doctor_start_booked" in str(exc.orig):
            raise SlotTakenError from exc
        raise
    return appointment
