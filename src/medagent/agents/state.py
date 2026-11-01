"""Graph state. Everything here is checkpointed per thread_id, so it survives restarts.

`messages` uses the `add_messages` reducer: nodes return *new* messages and LangGraph appends
them. The other keys are plain values that a node's update overwrites.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class DoctorOption(TypedDict):
    id: int
    name: str
    specialty: str
    city: str
    languages: list[str]


class Proposal(TypedDict):
    doctor_id: int
    doctor_name: str
    start_utc: str  # ISO 8601, UTC: what gets booked
    start_local: str  # human label in the clinic timezone: what the user confirms


class AppointmentOption(TypedDict):
    id: int
    doctor_name: str
    start_local: str


class BookingInfo(TypedDict):
    appointment_id: int
    doctor: str
    start: str  # human label in the clinic timezone, same as the confirmation card


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    # Per-turn values (reset by the guardrail at the start of every turn)
    route: str
    search_query_en: str  # English retrieval query for a non-English medical question, else ""
    safety_notice: bool
    booking: BookingInfo | None  # set only by the turn that booked an appointment
    draft: str  # the reply a node produced; output_guard checks it and turns it into a message
    draft_kind: str  # "medical" | "doctors" | "booking" | "emergency" | "info"
    # Conversation memory used across turns
    doctor_options: list[DoctorOption]
    booking_doctor_id: int | None
    proposal: Proposal | None
    appointment_options: list[AppointmentOption]
    cancel_proposal: AppointmentOption | None
