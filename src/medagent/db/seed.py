"""Synthetic seed data (doctors, weekly schedules, patients). Idempotent and deterministic.

* 15 hand-written doctors ported from the legacy project (always present, fixed values).
* ~85 more generated with Faker (de_DE) from a fixed seed, so every run, machine and CI job gets
  exactly the same doctors. Names are random first/last name combinations: any resemblance to
  real people is coincidental. No scraped or real data; patients are obviously fake.

`generate_doctor_specs` is pure (no DB); `seed` inserts whatever is missing.
"""

import random
from dataclasses import dataclass
from datetime import time

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from medagent.db.models import Doctor, DoctorSchedule, Patient
from medagent.schemas.specialty import Specialty

SEED_VALUE = 20261031  # fixed: change it and you change every generated doctor
TOTAL_DOCTORS = 100
WEEKDAYS = (0, 1, 2, 3, 4)  # Monday-Friday


@dataclass(frozen=True)
class Block:
    """Working hours (clinic-local) on the given weekdays."""

    weekdays: tuple[int, ...]
    start: time
    end: time


@dataclass(frozen=True)
class DoctorSpec:
    name: str
    specialty: str
    city: str
    languages: tuple[str, ...]
    blocks: tuple[Block, ...]


# ---------------------------------------------------------------- schedules
def _days(blocks: list[tuple[tuple[int, ...], time, time]]) -> tuple[Block, ...]:
    return tuple(Block(*b) for b in blocks)


FULL_DAY = _days([(WEEKDAYS, time(8), time(12)), (WEEKDAYS, time(13), time(17))])  # lunch 12-13
LONG_DAY = _days([(WEEKDAYS, time(8), time(20))])  # the legacy 08:00-20:00 default
PART_TIME = _days([((0, 2, 4), time(9), time(13)), ((1, 3), time(13), time(18))])

SCHEDULE_PATTERNS: list[tuple[Block, ...]] = [
    FULL_DAY,
    _days([(WEEKDAYS, time(8), time(12, 30)), (WEEKDAYS, time(13, 30), time(17, 30))]),
    _days([(WEEKDAYS, time(9), time(12)), (WEEKDAYS, time(14), time(18))]),  # long lunch
    _days([(WEEKDAYS, time(7), time(15))]),  # early shift, no break
    _days([(WEEKDAYS, time(11), time(19))]),  # late shift
    _days([((0, 1, 2, 3), time(8), time(12)), ((0, 1, 2, 3), time(13), time(16))]),  # 4-day week
    PART_TIME,
    _days([((1, 3), time(8), time(12)), ((4,), time(8), time(13))]),  # part-time mornings
    _days([((0, 2), time(14), time(19)), ((3,), time(9), time(13))]),
    LONG_DAY,
]

# ---------------------------------------------------------------- legacy doctors (fixed)
BERLIN_DE_EN = ("Berlin", ("German", "English"))
# (name, specialty, schedule)
LEGACY_DOCTORS: list[tuple[str, str, tuple[Block, ...]]] = [
    ("Dr. John Smith", "General Physician", LONG_DAY),
    ("Dr. Maria Garcia", "General Physician", FULL_DAY),
    ("Dr. Ahmed Khan", "General Physician", FULL_DAY),
    ("Dr. Emily Brown", "ENT Specialist", FULL_DAY),
    ("Dr. David Lee", "ENT Specialist", FULL_DAY),
    ("Dr. Michael Johnson", "Cardiologist", FULL_DAY),
    ("Dr. Sarah Wilson", "Cardiologist", PART_TIME),
    ("Dr. Olivia Martinez", "Dermatologist", FULL_DAY),
    ("Dr. Daniel Anderson", "Dermatologist", FULL_DAY),
    ("Dr. James Taylor", "Orthopedic", FULL_DAY),
    ("Dr. Sophia Thomas", "Orthopedic", FULL_DAY),
    ("Dr. Robert White", "Neurologist", FULL_DAY),
    ("Dr. Linda Harris", "Neurologist", PART_TIME),
    ("Dr. William Clark", "Dentist", FULL_DAY),
    ("Dr. Jessica Lewis", "Dentist", FULL_DAY),
]

# ---------------------------------------------------------------- generated doctors
SPECIALTIES = [s.value for s in Specialty]  # same order as before: keeps the seed identical
CITIES = [
    "Berlin",
    "Hamburg",
    "München",
    "Köln",
    "Frankfurt am Main",
    "Stuttgart",
    "Düsseldorf",
    "Leipzig",
    "Dresden",
    "Hannover",
]
EXTRA_LANGUAGES = ["Turkish", "Arabic", "Russian", "Spanish", "French", "Polish", "Italian"]


def generate_doctor_specs(seed: int = SEED_VALUE, total: int = TOTAL_DOCTORS) -> list[DoctorSpec]:
    """Deterministic: the same (seed, total) always yields the same list. No DB access."""
    fake = Faker("de_DE")
    fake.seed_instance(seed)
    rng = random.Random(seed)  # noqa: S311  (not security-related: reproducible fake data)

    specs = [
        DoctorSpec(name, specialty, BERLIN_DE_EN[0], BERLIN_DE_EN[1], blocks)
        for name, specialty, blocks in LEGACY_DOCTORS
    ]
    used = {s.name for s in specs}

    while len(specs) < total:
        name = f"Dr. {fake.first_name()} {fake.last_name()}"
        if name in used:
            continue
        used.add(name)
        languages = ["German"]
        if rng.random() < 0.8:
            languages.append("English")
        if rng.random() < 0.35:
            languages.append(rng.choice(EXTRA_LANGUAGES))
        # Round-robin for the first two passes so every specialty gets several doctors,
        # then random for the rest.
        n = len(specs) - len(LEGACY_DOCTORS)
        specialty = SPECIALTIES[n % len(SPECIALTIES)] if n < 2 * len(SPECIALTIES) else None
        specs.append(
            DoctorSpec(
                name=name,
                specialty=specialty or rng.choice(SPECIALTIES),
                city=rng.choice(CITIES),
                languages=tuple(languages),
                blocks=rng.choice(SCHEDULE_PATTERNS),
            )
        )
    return specs


# ---------------------------------------------------------------- patients
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

    for spec in generate_doctor_specs():
        doctor = session.scalars(select(Doctor).where(Doctor.name == spec.name)).one_or_none()
        if doctor is None:
            doctor = Doctor(
                name=spec.name,
                specialty=spec.specialty,
                city=spec.city,
                languages=list(spec.languages),
            )
            session.add(doctor)
            created["doctors"] += 1
        if not doctor.schedules:  # only seed hours for doctors without any
            for block in spec.blocks:
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
