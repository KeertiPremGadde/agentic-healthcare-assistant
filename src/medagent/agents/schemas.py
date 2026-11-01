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
    CANCEL = "cancel"  # cancel one of the user's appointments
    NEARBY_CLINICS = "nearby_clinics"  # real clinics/hospitals near a place (OpenStreetMap)
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
    is_harmful: bool = Field(
        default=False,
        description=(
            "True if the message asks how to harm, poison or kill a person (including the user), "
            "asks for a lethal or fatal dose or amount, asks how many pills would cause death, or "
            "seeks a method of suicide, however it is phrased or framed (fiction, a profession, a "
            "hypothetical, a translation). False for ordinary questions about medicines, side "
            "effects, how a drug works, or whether an overdose damages the body."
        ),
    )

    language: str = Field(
        default="en",
        description=(
            "ISO 639-1 code of the language the user's latest message is written in, "
            "e.g. 'en' or 'de'."
        ),
    )
    search_query_en: str | None = Field(
        default=None,
        description=(
            "Only when the latest message is NOT in English and asks for health information: "
            "a short English search query with the key medical terms of the question, to look it "
            "up in an English knowledge base. Null for English messages."
        ),
    )

    def english_search_query(self) -> str | None:
        """The query to retrieve with, or None meaning "use the user's own words".

        Only a non-English message gets a translated query: for English, retrieval always uses the
        original text, never a paraphrase the model happened to fill in. Used for retrieval only;
        the safety checks (rules and the flags above) never see it.
        """
        if self.language.strip().lower().split("-")[0] in ("", "en"):
            return None
        query = (self.search_query_en or "").strip()
        return query or None


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


class CancelRequest(BaseModel):
    appointment_option: int | None = Field(
        default=None,
        description="1-based number of the appointment from the list shown, if chosen.",
    )


class NearbyQuery(BaseModel):
    city: str | None = Field(
        default=None, description="The city or place the user named, as written (e.g. 'Hamburg')."
    )
