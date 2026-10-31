# 0004 – UTC storage, clinic-local schedules, DB-enforced slot uniqueness

Status: accepted (Phase 1)

## Context
The legacy bot used naive datetimes, hard-coded working hours in two places, and checked
availability in Python before inserting (a race: two users can both see a slot as free).

## Decision
- All timestamps are stored as `timestamptz` in UTC; naive datetimes raise `ValueError` in services.
- Working hours live in `doctor_schedules` as clinic-local wall-clock times; the clinic timezone is a
  setting (`CLINIC_TIMEZONE`, default `Europe/Berlin`). Slots are generated in local time, then
  converted to UTC, so daylight-saving changes are handled.
- Double booking is prevented by a **partial unique index** on `(doctor_id, start_time) WHERE
  status = 'booked'`; the repository maps the violation to `SlotTakenError`.
- Domain rules (`services/`) are pure functions returning typed results (`BookingError`), with no DB,
  clock or LLM access.

## Consequences
- Correct across DST and servers in any timezone; one place defines working hours.
- Concurrency-safe without locks; cancelled appointments free their slot but remain for audit.
- Known limitation: the repeated hour on the autumn DST change is bookable once. Overlapping
  bookings of different lengths would need an exclusion constraint (future work).
- Single clinic timezone for now; per-clinic timezones would move the setting into the data model.
