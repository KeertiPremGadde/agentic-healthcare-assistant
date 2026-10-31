# Public holidays: interview Q&A

What we built: doctors are closed on the public holidays of their own city, enforced in the pure
availability and validation services and in the booking tool. Code:
`src/medagent/services/public_holidays.py`, `availability.py`, `validation.py`,
`tools/clinic.py`. Decision: [ADR 0010](../adr/0010-public-holidays-per-city.md).

---

### Why per city and not just "German holidays"?
German public holidays are set by the federal states, and a few depend on the municipality. On
31 October 2025 (a Friday) Leipzig is closed for Reformation Day and Berlin is open; Corpus Christi
closes Köln but not Hamburg. A national calendar would be wrong for most dates that matter.

### How did you keep the services pure?
They don't know about cities or the `holidays` library. They take an optional function
`holiday_on(day) -> name | None`. `ClinicService` builds it from the doctor's city and passes it
in. The services stay deterministic and testable with a one-line fake calendar, and leaving the
parameter out keeps the old behaviour, so none of the existing tests changed.

### What was tricky about München and Assumption Day?
The library has no "Bavaria with Assumption Day" subdivision; it models the Catholic exception as a
*category*. Enabling that category globally would also add Corpus Christi to Saxony and Thuringia
and wrongly close Leipzig and Dresden. So the city table has a `catholic` flag that is set only for
München, and a test pins both facts: 15 August closes München but not Nürnberg or Berlin, and
4 June closes Köln but not Leipzig. I checked the library's actual data instead of trusting my memory.

### In what order are the reasons checked, and why?
In the past, then no working hours that weekday, then public holiday, then off-grid, then already
booked. A Sunday that is also a holiday should say "doesn't work on Sundays" because that is the
true, schedule-based reason, and weekends stay closed through the schedules, not the calendar.

### Where is it enforced?
In the availability service (no slots on a holiday), in `validate_slot` (`public_holiday`) and
therefore in `check_slot` and `book_appointment`. The booking tool re-validates, so calling it
directly over MCP can't book a closed day either, not only the conversation. Tests prove it with a
direct tool call.

### How do the tests stay honest?
Pinned real dates from the library (Christmas in every year and city, Easter Monday moving each
year, 31 October for Leipzig versus Berlin on a Friday, Corpus Christi, Epiphany, Women's Day,
Repentance and Prayer Day, Assumption Day for three years), plus the day before and after. A
completeness test fails if a seeded city is missing from the table, so a new city can't silently get
only national holidays. Mutation checks: ignoring the city's calendar fails 8 integration tests;
ignoring holidays in validation fails 9.

### What does it not do?
Practice holidays and a doctor's own time off (that needs a time-off table), bridge days, school
holidays, and 24 and 31 December (not public holidays). The library is community data, so the
README says it isn't an official calendar.

### What would you do next?
A per-doctor time-off table feeding the same lookup, and an optional data check against an official
source in CI.
