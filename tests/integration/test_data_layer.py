from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medagent.db import repository
from medagent.db.models import Appointment, AppointmentStatus, Doctor, DoctorSchedule, Patient
from medagent.db.seed import seed
from medagent.services.availability import free_slots
from medagent.services.validation import BookingError, validate_slot

pytestmark = pytest.mark.integration

BERLIN = ZoneInfo("Europe/Berlin")
START = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


@pytest.fixture
def doctor_and_patient(session: Session) -> tuple[Doctor, Patient]:
    doctor = Doctor(name="Dr. Test", specialty="Cardiologist")
    patient = Patient(name="Pat Example", email="pat@example.com")
    session.add_all([doctor, patient])
    session.commit()
    return doctor, patient


def test_seed_is_idempotent(session: Session) -> None:
    first = seed(session)
    second = seed(session)
    assert first["doctors"] == 15
    assert first["patients"] == 5
    assert first["schedules"] > 0
    assert second == {"doctors": 0, "schedules": 0, "patients": 0}
    assert session.scalar(select(func.count()).select_from(Doctor)) == 15


def test_double_booking_is_rejected_by_the_database(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, patient = doctor_and_patient
    repository.create_appointment(session, patient.id, doctor.id, START)
    with pytest.raises(repository.SlotTakenError):
        repository.create_appointment(session, patient.id, doctor.id, START)


def test_cancelled_appointment_frees_the_slot(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, patient = doctor_and_patient
    first = repository.create_appointment(session, patient.id, doctor.id, START)
    first.status = AppointmentStatus.CANCELLED
    session.commit()
    again = repository.create_appointment(session, patient.id, doctor.id, START)
    assert again.id != first.id


def test_same_time_with_another_doctor_is_fine(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, patient = doctor_and_patient
    other = Doctor(name="Dr. Other", specialty="Dentist")
    session.add(other)
    session.commit()
    repository.create_appointment(session, patient.id, doctor.id, START)
    repository.create_appointment(session, patient.id, other.id, START)


def test_timestamps_roundtrip_as_utc_and_defaults_are_set(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, patient = doctor_and_patient
    appt = repository.create_appointment(
        session, patient.id, doctor.id, datetime(2026, 11, 3, 10, 0, tzinfo=BERLIN)
    )
    session.expire_all()
    stored = session.get(Appointment, appt.id)
    assert stored is not None
    assert stored.start_time == datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
    assert stored.status is AppointmentStatus.BOOKED
    assert stored.created_at.tzinfo is not None
    assert stored.updated_at >= stored.created_at


def test_database_rejects_invalid_status(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, patient = doctor_and_patient
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO appointments (patient_id, doctor_id, start_time, status) "
                "VALUES (:p, :d, now(), 'bogus')"
            ),
            {"p": patient.id, "d": doctor.id},
        )


def test_database_rejects_invalid_schedule(
    session: Session, doctor_and_patient: tuple[Doctor, Patient]
) -> None:
    doctor, _ = doctor_and_patient
    session.add(
        DoctorSchedule(doctor_id=doctor.id, weekday=7, start_time=time(8), end_time=time(9))
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_availability_pipeline_end_to_end(session: Session) -> None:
    """DB rows -> pure services: the booked slot disappears and validation agrees."""
    seed(session)
    doctor = repository.get_doctors(session, "Cardiologist")[0]
    windows = repository.get_working_windows(session, doctor.id)
    patient = session.scalars(select(Patient)).first()
    assert patient is not None
    day = date(2026, 11, 3)  # Tuesday
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    target = free_slots(day, windows, [], now, BERLIN, 30)[0]
    repository.create_appointment(session, patient.id, doctor.id, target)

    booked = repository.get_booked_starts(session, doctor.id, day, BERLIN)
    assert booked == [target]
    assert target not in free_slots(day, windows, booked, now, BERLIN, 30)
    assert validate_slot(target, windows, booked, now, BERLIN, 30) is BookingError.ALREADY_BOOKED
