"""The logged-in user's own appointments. The patient is derived from the token, so there is no
way to name someone else's; another user's appointment id answers 404."""

from fastapi import APIRouter

from medagent.api.deps import CurrentUserDep, ResourcesDep
from medagent.api.errors import ApiError
from medagent.api.schemas import AppointmentOut, ErrorResponse

router = APIRouter(prefix="/v1/appointments", tags=["appointments"])


@router.get(
    "",
    response_model=list[AppointmentOut],
    summary="My upcoming appointments",
    responses={401: {"model": ErrorResponse}},
)
async def list_appointments(user: CurrentUserDep, res: ResourcesDep) -> list[AppointmentOut]:
    result = await res.clinic.list_appointments(user.patient_id)
    return [
        AppointmentOut(
            id=a.id,
            doctor_id=a.doctor_id,
            doctor_name=a.doctor_name,
            start=a.start,
            status=a.status,
        )
        for a in result.appointments
    ]


@router.delete(
    "/{appointment_id}",
    status_code=204,
    summary="Cancel one of my appointments",
    description="An explicit, authenticated action by the user, so it needs no extra "
    "confirmation step (the chat flow asks first). Also removes the calendar event, if any.",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_appointment(appointment_id: int, user: CurrentUserDep, res: ResourcesDep) -> None:
    result = await res.clinic.cancel_appointment(user.patient_id, appointment_id)
    if result.ok:
        return
    if result.error == "not_cancellable":
        raise ApiError(
            409, "not_cancellable", "That appointment has started or is already cancelled."
        )
    raise ApiError(404, "not_found", "Appointment not found.")
