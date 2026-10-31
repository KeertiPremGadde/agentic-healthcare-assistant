"""Structured-output schemas for the LLM calls in the graph. The model fills these in; code
never parses free text to decide a route, a specialty or a booking."""

import enum
from typing import Literal

from pydantic import BaseModel, Field

from medagent.schemas.specialty import Specialty


class Route(enum.StrEnum):
    MEDICAL_QUESTION = "medical_question"  # health information -> RAG
    FIND_DOCTOR = "find_doctor"  # symptoms -> which specialist / list doctors
    BOOK = "book"  # book, or continue booking, an appointment
    SMALLTALK = "smalltalk"  # greetings, thanks, "what can you do?"
    OUT_OF_SCOPE = "out_of_scope"  # anything else


class RouteDecision(BaseModel):
    route: Route
    is_emergency: bool = Field(
        description=(
            "True only if the user or someone with them may be in acute danger right now "
            "(e.g. severe chest pain, can't breathe, stroke signs, suicidal intent)."
        )
    )


class DoctorQuery(BaseModel):
    specialty: Specialty = Field(description="The most appropriate specialty for the symptoms.")
    city: str | None = Field(default=None, description="City the user asked for, if any.")
    language: str | None = Field(
        default=None, description="Language the doctor should speak, in English (e.g. 'Turkish')."
    )


class BookingRequest(BaseModel):
    doctor_option: int | None = Field(
        default=None, description="1-based number of a doctor from the list shown, if chosen."
    )
    doctor_name: str | None = Field(default=None, description="Doctor's name if given by name.")
    date: str | None = Field(
        default=None, description="Requested day as YYYY-MM-DD, resolved from today's date."
    )
    time_of_day: Literal["morning", "afternoon", "evening"] | None = None
    exact_time: str | None = Field(default=None, description="Exact time as HH:MM (24-hour).")
