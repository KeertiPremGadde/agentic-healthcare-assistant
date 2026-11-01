"""Request and response models of the public API (these become the OpenAPI documentation)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = r"^[a-zA-Z0-9_-]{3,32}$"


class RegisterRequest(BaseModel):
    username: str = Field(
        pattern=USERNAME_PATTERN,
        description="3-32 letters, digits, '_' or '-'. Not an email, not your real name.",
        examples=["demo-patient-1"],
    )
    password: str = Field(
        min_length=10,
        max_length=128,
        description="At least 10 characters. Stored only as an Argon2 hash.",
        examples=["a-long-demo-password"],
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (the OAuth2 scheme name)
    expires_in: int = Field(description="Seconds until the token expires.")


class UserOut(BaseModel):
    username: str
    patient_id: int = Field(description="The synthetic patient record bookings are made for.")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="Your message (length limit: see /v1/limits).")
    conversation_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Omit to start a conversation; send the returned id to continue it.",
    )

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ResumeRequest(BaseModel):
    confirmed: bool = Field(description="true = go ahead (book/cancel), false = don't.")


class DoctorOut(BaseModel):
    id: int
    name: str
    specialty: str
    city: str
    languages: list[str]


class BookingOut(BaseModel):
    appointment_id: int
    doctor: str
    start: str = Field(description="Date and time in the clinic's timezone, as shown to the user.")


class ChatResponse(BaseModel):
    """What `stream=false` returns (the SSE stream carries the same information as events)."""

    conversation_id: str
    reply: str | None = Field(description="The assistant's reply, or null while waiting for you.")
    kind: Literal["normal", "booked", "emergency", "harmful_intent"] = Field(
        default="normal", description="How to present the reply (e.g. a crisis card)."
    )
    appointment_id: int | None = Field(default=None, description="Set when this turn booked one.")
    booking: BookingOut | None = Field(default=None, description="Details of that booking.")
    doctors: list[DoctorOut] | None = Field(
        default=None,
        description="Set when the reply suggests doctors; the user's 'Book number N' refers to "
        "the Nth entry.",
    )
    pending: dict[str, Any] | None = Field(
        description="Set when the assistant needs a yes/no: call /resume with your answer."
    )
    usage: "UsageOut"


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class HistoryResponse(BaseModel):
    conversation_id: str
    messages: list[MessageOut]
    pending: dict[str, Any] | None


class AppointmentOut(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    start: datetime = Field(description="Start time, timezone-aware (UTC).")
    status: str


class LimitsOut(BaseModel):
    max_message_chars: int
    daily_message_limit: int
    messages_used_today: int
    demo_notice: str


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code, e.g. 'demo_limit_reached'.")
    message: str = Field(description="Human-readable message, safe to show to users.")
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


ChatResponse.model_rebuild()
