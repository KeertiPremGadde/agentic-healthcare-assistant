"""Synthetic seed data (doctors, weekly schedules, patients). Idempotent: safe to re-run.

Doctors are ported from the legacy project. Patients are obviously fake (example.com emails,
reserved fictional phone numbers); never put real personal data here.
"""

from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from medagent.db.models import Doctor, DoctorSchedule, Patient

WEEKDAYS = (0, 1, 2, 3, 4)  # Monday-Friday

# (name, specialty)
DOCTORS: list[tuple[str, str]] = [
    ("Dr. John Smith", "General Physician"),
    ("Dr. Maria Garcia", "General Physician"),
    ("Dr. Ahmed Khan", "General Physician"),
    ("Dr. Emily Brown", "ENT Specialist"),
    ("Dr. David Lee", "ENT Specialist"),
    ("Dr. Michael Johnson", "Cardiologist"),
    ("Dr. Sarah Wilson", "Cardiologist"),
    ("Dr. Olivia Martinez", "Dermatologist"),
    ("Dr. Daniel Anderson", "Dermatologist"),
    ("Dr. James Taylor", "Orthopedic"),
    ("Dr. Sophia Thomas", "Orthopedic"),
    ("Dr. Robert White", "Neurologist"),
    ("Dr. Linda Harris", "Neurologist"),
    ("Dr. William Clark", "Dentist"),
    ("Dr. Jessica Lewis", "Dentist"),
]


@dataclass(frozen=True)
class Block:
    weekdays: tuple[int, ...]
    start: time
    end: time


FULL_DAY = [Block(WEEKDAYS, time(8), time(12)), Block(WEEKDAYS, time(13), time(17))]
LONG_DAY = [Block(WEEKDAYS, time(8), time(20))]  # the legacy 08:00-20:00 default
PART_TIME = [
    Block((0, 2, 4), time(9), time(13)),  # Mon/Wed/Fri mornings
    Block((1, 3), time(13), time(18)),  # Tue/Thu afternoons
]

# Anyone not listed gets FULL_DAY.
SCHEDULE_OVERRIDES: dict[str, list[Block]] = {
    "Dr. John Smith": LONG_DAY,
    "Dr. Sarah Wilson": PART_TIME,
    "Dr. Linda Harris": PART_TIME,
}

# (name, age, gender, phone, email) - all fictional
PATIENTS: list[tuple[str, int, str, str, str]] = [
    ("Alex Example", 34, "female", "+49 30 5550 0101", "alex.example@example.com"),
    ("Sam Sample", 52, "male", "+49 30 5550 0102", "sam.sample@example.com"),
    ("Jo Testperson", 28, "other", "+49 30 5550 0103", "jo.testperson@example.com"),
    ("Pat Placeholder", 67, "female", "+49 30 5550 0104", "pat.placeholder@example.com"),
    ("Chris Fakename", 41, "male", "+49 30 5550 0105", "chris.fakename@example.com"),
]


def seed(session: Session) -> dict[str, int]:
    """Insert whatever is missing; return how many rows of each kind were created."""
    created = {"doctors": 0, "schedules": 0, "patients": 0}

    for name, specialty in DOCTORS:
        doctor = session.scalars(select(Doctor).where(Doctor.name == name)).one_or_none()
        if doctor is None:
            doctor = Doctor(name=name, specialty=specialty)
            session.add(doctor)
            created["doctors"] += 1
        if not doctor.schedules:  # only seed hours for doctors without any
            for block in SCHEDULE_OVERRIDES.get(name, FULL_DAY):
                for weekday in block.weekdays:
                    doctor.schedules.append(
                        DoctorSchedule(weekday=weekday, start_time=block.start, end_time=block.end)
                    )
                    created["schedules"] += 1

    for name, age, gender, phone, email in PATIENTS:
        if session.scalars(select(Patient).where(Patient.email == email)).one_or_none() is None:
            session.add(Patient(name=name, age=age, gender=gender, phone=phone, email=email))
            created["patients"] += 1

    session.commit()
    return created
