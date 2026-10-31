"""Thin DB access used by tools and the API. Domain rules live in `services/`."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medagent.db.models import Appointment, AppointmentStatus, Doctor, DoctorSchedule, Patient
from medagent.services.availability import WorkingWindow, clinic_day_bounds


class SlotTakenError(Exception):
    """Raised when the unique index rejects a double booking."""


def get_doctors(
    session: Session,
    specialty: str | None = None,
    city: str | None = None,
    language: str | None = None,
) -> list[Doctor]:
    stmt = select(Doctor).order_by(Doctor.id)
    if specialty:
        stmt = stmt.where(Doctor.specialty == specialty)
    if city:
        stmt = stmt.where(Doctor.city == city)
    if language:
        stmt = stmt.where(Doctor.languages.contains([language]))
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


def get_doctor(session: Session, doctor_id: int) -> Doctor | None:
    return session.get(Doctor, doctor_id)


def find_doctors_by_name(session: Session, name: str, limit: int = 5) -> list[Doctor]:
    """Case-insensitive match on the name without the "Dr." title; every word must appear."""
    words = [w for w in name.replace("Dr.", " ").replace("dr.", " ").split() if len(w) > 1]
    if not words:
        return []
    stmt = select(Doctor).order_by(Doctor.id).limit(limit)
    for word in words:
        stmt = stmt.where(Doctor.name.ilike(f"%{word}%"))
    return list(session.scalars(stmt))


def get_patient_by_email(session: Session, email: str) -> Patient | None:
    return session.scalars(select(Patient).where(Patient.email == email)).one_or_none()


def get_appointment(session: Session, appointment_id: int) -> Appointment | None:
    return session.get(Appointment, appointment_id)


def list_patient_appointments(
    session: Session, patient_id: int, after: datetime | None = None
) -> list[tuple[Appointment, Doctor]]:
    """A patient's booked appointments (optionally only those starting after `after`)."""
    stmt = (
        select(Appointment, Doctor)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .where(Appointment.patient_id == patient_id, Appointment.status == AppointmentStatus.BOOKED)
        .order_by(Appointment.start_time)
    )
    if after is not None:
        stmt = stmt.where(Appointment.start_time > after)
    return [(a, d) for a, d in session.execute(stmt).all()]
