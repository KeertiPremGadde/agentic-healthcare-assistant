from medagent.db.seed import (
    CITIES,
    LEGACY_DOCTORS,
    SEED_VALUE,
    SPECIALTIES,
    TOTAL_DOCTORS,
    generate_doctor_specs,
)
from medagent.services.availability import WorkingWindow, generate_slots


def test_generation_is_deterministic() -> None:
    assert generate_doctor_specs() == generate_doctor_specs()


def test_a_different_seed_gives_different_doctors() -> None:
    assert generate_doctor_specs(SEED_VALUE + 1) != generate_doctor_specs()


def test_legacy_doctors_come_first_and_are_unchanged() -> None:
    specs = generate_doctor_specs()
    for spec, (name, specialty, blocks) in zip(specs, LEGACY_DOCTORS, strict=False):
        assert (spec.name, spec.specialty, spec.blocks) == (name, specialty, blocks)
        assert spec.city == "Berlin"


def test_total_and_unique_names() -> None:
    specs = generate_doctor_specs()
    assert len(specs) == TOTAL_DOCTORS == 100
    assert len({s.name for s in specs}) == len(specs)


def test_at_least_15_specialties_and_every_legacy_one_included() -> None:
    specs = generate_doctor_specs()
    used = {s.specialty for s in specs}
    assert len(used) >= 15
    assert used == set(SPECIALTIES)
    assert {sp for _, sp, _ in LEGACY_DOCTORS} <= used


def test_every_doctor_has_languages_city_and_valid_schedule() -> None:
    for spec in generate_doctor_specs():
        assert spec.languages[0] == "German"
        assert len(set(spec.languages)) == len(spec.languages)
        assert spec.city in CITIES
        assert spec.blocks
        for block in spec.blocks:
            assert block.end > block.start
            assert block.weekdays
            assert all(0 <= d <= 6 for d in block.weekdays)


def test_schedules_are_varied() -> None:
    specs = generate_doctor_specs()
    assert len({s.blocks for s in specs}) >= 6
    assert any(len(s.blocks) == 1 for s in specs)  # no lunch break (single block)
    assert any(len(s.blocks) > 1 for s in specs)  # lunch break (two blocks)
    assert any(len({d for b in s.blocks for d in b.weekdays}) < 5 for s in specs)  # part-time
    assert {"English", "German"} <= {lang for s in specs for lang in s.languages}
    assert len({lang for s in specs for lang in s.languages}) >= 4


def test_generated_schedules_produce_slots() -> None:
    from datetime import date
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Berlin")
    for spec in generate_doctor_specs():
        windows = [WorkingWindow(d, b.start, b.end) for b in spec.blocks for d in b.weekdays]
        week = [generate_slots(date(2026, 11, 2 + i), windows, tz, 30) for i in range(7)]
        assert any(week)
