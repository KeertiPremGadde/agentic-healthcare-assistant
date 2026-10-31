"""Typed inputs/outputs of the clinic tools. Shared by the in-process implementation, the MCP
server (where they become the tools' JSON output schemas) and the MCP client."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TimeOfDay = Literal["morning", "afternoon", "evening"]


class DoctorInfo(BaseModel):
    id: int
    name: str
    specialty: str
    city: str
    languages: list[str]


class DoctorList(BaseModel):
    doctors: list[DoctorInfo]


class Availability(BaseModel):
    doctor_id: int
    slots: list[datetime] = Field(description="Free slot start times, timezone-aware (UTC).")
    works_on_from_day: bool = Field(
        default=True,
        description="Whether the doctor has working hours on the weekday of `from_day`. When "
        "false, no slot exists that day however free the diary is (a day off, not a full day).",
    )
    holiday: str | None = Field(
        default=None,
        description="Name of the public holiday on `from_day` in the doctor's city (e.g. "
        "'Reformation Day'), or null on an ordinary day. The practice is closed on a holiday.",
    )


class SlotCheck(BaseModel):
    ok: bool
    error: str | None = Field(
        default=None,
        description="in_the_past | not_a_working_day | public_holiday | outside_working_hours "
        "| already_booked",
    )
    detail: str | None = Field(
        default=None, description="For public_holiday: the holiday's name, e.g. 'Reformation Day'."
    )


class BookingResult(BaseModel):
    ok: bool
    appointment_id: int | None = None
    start: datetime | None = None
    error: str | None = Field(default=None, description="A SlotCheck error, or unknown_doctor.")
    detail: str | None = Field(
        default=None, description="For public_holiday: the holiday's name, e.g. 'Reformation Day'."
    )
    calendar_event_id: str | None = Field(
        default=None, description="Set if the optional calendar step succeeded."
    )


class AppointmentInfo(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    start: datetime
    status: str


class AppointmentList(BaseModel):
    appointments: list[AppointmentInfo]


class CancelResult(BaseModel):
    ok: bool
    error: str | None = Field(default=None, description="not_found | not_cancellable")


class NearbyClinic(BaseModel):
    name: str
    kind: str = Field(description="clinic | doctors | hospital (OpenStreetMap amenity)")
    address: str | None = None
    website: str | None = None
    lat: float
    lon: float
    osm_url: str


class NearbyClinics(BaseModel):
    """Real places from OpenStreetMap. Never bookable (only the demo clinic's doctors are)."""

    city: str
    clinics: list[NearbyClinic]
    bookable: Literal[False] = False
    attribution: str = (
        "© OpenStreetMap contributors (ODbL), https://www.openstreetmap.org/copyright"
    )
    from_cache: bool = False
    error: str | None = None
