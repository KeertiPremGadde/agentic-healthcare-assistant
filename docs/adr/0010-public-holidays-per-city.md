# 0010 – Public holidays per city

Status: accepted (follow-up after Phase 5)

## Context
Doctors were bookable on any weekday inside their working hours, including public holidays. In
Germany the holidays are set by the federal states, and a few depend on the municipality, so
a practice is closed on the holidays of **its own city**: on 31 October 2025 (a Friday) a doctor in
Leipzig is closed (Reformation Day) while one in Berlin is open.

## Decision

### 1. Data: the `holidays` library, per city
`holidays` (MIT, version 0.107, pure Python, no network) provides the German calendar with a
subdivision for every state and names in English and German. It is a runtime dependency. It is
open-source community data, not an official calendar, and the README says so.

### 2. A static city table with a completeness test (no migration)
`services/public_holidays.py` maps each city to a `Region(subdiv, catholic)`: the state code plus
whether the municipality is predominantly Catholic. The 10 seeded cities are covered, plus
Nürnberg as the contrast to München; common ASCII and English spellings are aliases; an unknown or
missing city gets the national holidays only. A test fails if a seeded city is missing, so a new
city can't silently fall back to national holidays. Alternative rejected: a `Doctor.state` column
with a migration, which adds a second source of truth for something derivable from `city`.

### 3. München observes Assumption Day: the `catholic` category, switched on per city
There is no "BYP" subdivision. The library models the Catholic exception as a *category*: for
Bavaria, `categories=("public", "catholic")` adds Assumption Day (15 August); the `Augsburg`
subdivision includes it as well. The same category also adds **Corpus Christi to Saxony and
Thuringia**, which Leipzig and Dresden do not observe, so the category must never be global. The
table therefore carries a `catholic` flag, set only for München (a test pins that). Verified:
15 Aug 2025: München closed (Assumption Day), Nürnberg and Berlin open; 4 Jun 2026: Leipzig open,
Köln closed (Corpus Christi).

### 4. Pure services take an optional lookup; the order of reasons is fixed
`generate_slots`, `free_slots` and `validate_slot` take an optional `holiday_on(day) -> name | None`
(a plain function, so the services stay pure and city-agnostic). On a holiday there are no slots,
and validation returns the new reason `public_holiday`. The order is: in the past, **no working
hours that weekday** (so a Sunday that is also a holiday says "doesn't work on Sundays"), **public
holiday**, off-grid time, already booked. Weekends stay closed through the schedules, not the
calendar. Omitting the lookup keeps the old behaviour (all existing tests are unchanged).

### 5. Where it is enforced
`ClinicService` builds the lookup from the doctor's city, so every route in is covered:
`check_availability` returns no slots on a holiday and reports `holiday` (name) next to
`works_on_from_day`; `check_slot` and `book_appointment` return `public_holiday` with the name in
`detail`. The booking tool re-validates, so a direct call over MCP cannot book a closed day.
The booking node uses the same message pattern as the day-off fix: "Dr. X's practice is closed on
Fri 31 Oct 2025 (Reformation Day). Shall I book Mon 3 Nov 2025, 08:00 with Dr. X?"
Names follow `HOLIDAY_LANGUAGE` (`en_US` default, or `de`: "Reformationstag"), also passed to the
MCP server process.

## Not modelled (deliberately)
- Practice holidays and personal time off (a future per-doctor time-off table).
- Bridge days, school holidays, and 24 and 31 December: many practices close, but they are not
  public holidays.
- Municipal exceptions beyond the Catholic flag (e.g. Augsburg's Peace Festival is in the library
  as the `Augsburg` subdivision but no seeded city uses it). The table is the place to add them.
- The library is community-maintained: holiday rules can change (Berlin added Women's Day in 2019
  and one-off days exist). Upgrading `holidays` updates the data; the pinned tests would flag a
  change in any date we assert.

## Consequences
- Doctors in different cities have different availability on the same day, which is correct and
  now visible to the agent and the API.
- No schema change, no new LLM calls, no prompt changes.
- The city table is data to maintain; its completeness test and the pinned dates are how it stays
  honest. Cities outside Germany or missing from the table get national holidays only.
