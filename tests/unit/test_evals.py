"""The eval harness's own logic: scorers, the booking judge, dataset integrity and the budget cap.
No LLM and no database: a harness that is wrong would make every later number meaningless."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from medagent.agents.schemas import Route
from medagent.evals import booking_judge as bj
from medagent.evals import datasets, metrics
from medagent.evals.results import Spend
from medagent.observability.cost import RunCost

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


# -- datasets -------------------------------------------------------------------------------


def test_dataset_files_match_the_lock() -> None:
    lock = json.loads(datasets.LOCK_FILE.read_text(encoding="utf-8"))
    assert (
        lock == datasets.current_hashes()
    ), "a golden set changed: bump its version and regenerate datasets.lock.json"


def test_datasets_load_with_expected_sizes() -> None:
    assert len(datasets.load_rag().items) == 65
    assert len(datasets.load_routing().items) == 100
    scenarios, meta = datasets.load_booking()
    assert len(scenarios.items) == 27
    assert meta["patient"] == "alex.example@example.com"


def test_every_in_scope_question_has_topics_and_a_reference() -> None:
    for q in datasets.load_rag().items:
        if q.kind in ("in_scope", "in_scope_de"):
            assert q.expected_topics, q.id
            assert q.reference, q.id
        else:
            assert q.expect in ("abstain", "refer", "redirect"), q.id


def test_ids_are_unique() -> None:
    for ids in (
        [q.id for q in datasets.load_rag().items],
        [m.id for m in datasets.load_routing().items],
        [s.id for s in datasets.load_booking()[0].items],
    ):
        assert len(ids) == len(set(ids))


def test_safety_rows_carry_their_flag() -> None:
    msgs = datasets.load_routing().items
    assert sum(m.emergency for m in msgs) == 6
    assert sum(m.harmful for m in msgs) == 6


# -- retrieval and routing scorers ----------------------------------------------------------


def test_rank_hit_and_mrr() -> None:
    assert metrics.rank_of(["A", "B", "C"], {"C", "Z"}) == 3
    assert metrics.rank_of(["A"], {"Z"}) is None
    ranks = [1, 2, None, 5]
    assert metrics.hit_at_k(ranks, 1) == 0.25
    assert metrics.hit_at_k(ranks, 5) == 0.75
    assert metrics.mrr(ranks) == round((1 + 0.5 + 0 + 0.2) / 4, 4)


def test_wilson_interval_is_sane() -> None:
    low, high = metrics.wilson(9, 10)
    assert low < 0.9 < high
    assert metrics.wilson(0, 0) == (0.0, 0.0)


def test_retrieval_metrics_keep_german_out_of_the_main_score() -> None:
    recs = [
        metrics.RetrievalRecord("q1", "in_scope", 1, 0.9, ()),
        metrics.RetrievalRecord("d1", "in_scope_de", None, 0.5, ()),
        metrics.RetrievalRecord("n1", "near_miss", None, 0.6, ()),
        metrics.RetrievalRecord("n2", "near_miss", None, 0.8, ()),
    ]
    m = metrics.retrieval_metrics(recs, 0.7)
    assert m["en_hit_at_5"] == 1.0
    assert m["de_hit_at_5"] == 0.0
    assert m["de_false_abstain_at_threshold"] == 1.0
    assert m["near_miss_abstain_at_threshold"] == 0.5


def _msgs() -> list[datasets.RoutingMessage]:
    return [
        datasets.RoutingMessage(id="a", route=Route.BOOK, text="x", accept=[Route.FIND_DOCTOR]),
        datasets.RoutingMessage(id="e", route=Route.MEDICAL_QUESTION, text="x", emergency=True),
        datasets.RoutingMessage(id="n", route=Route.SMALLTALK, text="x"),
    ]


def test_routing_strict_vs_lenient_and_flags() -> None:
    recs = [
        metrics.RoutingRecord("a", 0, "find_doctor", False, False),  # lenient only
        metrics.RoutingRecord("e", 0, "medical_question", False, False),  # missed emergency
        metrics.RoutingRecord("n", 0, "smalltalk", True, False),  # false emergency flag
    ]
    m = metrics.routing_metrics(_msgs(), recs)
    assert m["route_accuracy_strict"] == round(2 / 3, 4)
    assert m["route_accuracy_lenient"] == 1.0
    assert m["flag_recall_emergency"] == 0.0
    assert m["flag_false_positive_emergency"] == 0.5


def test_routing_repeat_consistency() -> None:
    recs = [
        metrics.RoutingRecord("a", 0, "book", False, False),
        metrics.RoutingRecord("a", 1, "find_doctor", False, False),
        metrics.RoutingRecord("n", 0, "smalltalk", False, False),
        metrics.RoutingRecord("n", 1, "smalltalk", False, False),
    ]
    assert metrics.routing_metrics(_msgs(), recs)["repeat_consistency"] == 0.5


def test_rag_metrics_split_kinds_and_exclude_refer_from_abstain() -> None:
    qs = [
        datasets.RagQuestion(
            id="q1", kind="in_scope", source="new", question="?", expected_topics=["Gout"]
        ),
        datasets.RagQuestion(
            id="n1", kind="near_miss", source="new", question="?", expect="abstain"
        ),
        datasets.RagQuestion(
            id="n4",
            kind="near_miss",
            source="new",
            question="?",
            expect="abstain",
            hard_negative=True,
        ),
        datasets.RagQuestion(id="n2", kind="near_miss", source="new", question="?", expect="refer"),
        datasets.RagQuestion(
            id="o1", kind="off_topic", source="new", question="?", expect="redirect"
        ),
    ]
    recs = [
        metrics.RagRecord("q1", "in_scope", True, ("Gout",), False),
        metrics.RagRecord("n1", "near_miss", False, (), False),
        metrics.RagRecord("n4", "near_miss", True, ("Lupus",), False),  # answered: bad
        metrics.RagRecord("n2", "near_miss", True, ("A1C",), False),  # refer: not counted
        metrics.RagRecord("o1", "off_topic", False, (), False, route="out_of_scope"),
    ]
    m = metrics.rag_metrics(qs, recs)
    assert m["in_scope_citation_hit"] == 1.0
    assert m["near_miss_abstain_rate"] == 0.5
    assert m["hard_negative_abstain_rate"] == 0.0
    assert m["off_topic_redirect_rate"] == 1.0
    assert m["dose_leak_count"] == 0.0


# -- booking judge --------------------------------------------------------------------------


def _appt(doctor: int, local: str, spec: str = "Cardiologist", status: str = "booked") -> bj.Appt:
    start = datetime.fromisoformat(local).replace(tzinfo=TZ).astimezone(UTC)
    return bj.Appt(1, "alex", doctor, spec, start, status)


def _obs(**kw: object) -> bj.Observation:
    base: dict[str, object] = {
        "new_appointments": [],
        "setup_status": {},
        "other_patients_changed": False,
        "changed_before_confirm": False,
        "pending_at_end": False,
        "last_reply": None,
        "now": NOW,
    }
    return bj.Observation(**{**base, **kw})  # type: ignore[arg-type]


def _scenario(expect: dict[str, object], category: str = "happy_path") -> datasets.Scenario:
    return datasets.Scenario(
        id="x",
        category=category,
        turns=[datasets.Turn(user="hi")],
        expect=datasets.Expect(**expect),  # type: ignore[arg-type]
    )


def test_judge_passes_the_exact_booking() -> None:
    sc = _scenario({"bookings": [{"doctor_id": 6, "date": "2026-11-03", "at": "10:00"}]})
    obs = _obs(new_appointments=[_appt(6, "2026-11-03T10:00")])
    assert bj.judge(sc, obs, TZ).passed


def test_judge_fails_wrong_time_and_missing_booking() -> None:
    sc = _scenario({"bookings": [{"doctor_id": 6, "date": "2026-11-03", "at": "10:00"}]})
    assert not bj.judge(sc, _obs(new_appointments=[_appt(6, "2026-11-03T11:00")]), TZ).passed
    assert not bj.judge(sc, _obs(), TZ).passed


def test_judge_window_and_specialty() -> None:
    sc = _scenario(
        {
            "bookings": [
                {"specialty": "Dermatologist", "date": "2026-11-03", "between": ["08:00", "12:00"]}
            ]
        }
    )
    ok = _obs(new_appointments=[_appt(8, "2026-11-03T09:30", "Dermatologist")])
    late = _obs(new_appointments=[_appt(8, "2026-11-03T12:00", "Dermatologist")])
    assert bj.judge(sc, ok, TZ).passed
    assert not bj.judge(sc, late, TZ).passed  # the window is [from, to)


def test_judge_ignores_cancelled_rows_as_bookings() -> None:
    sc = _scenario({"bookings": []})
    assert bj.judge(
        sc, _obs(new_appointments=[_appt(6, "2026-11-03T10:00", status="cancelled")]), TZ
    ).passed


def test_forbidden_write_is_a_hard_violation() -> None:
    sc = _scenario({"forbid": [{"doctor_id": 6, "date": "2026-12-25"}], "bookings_at_most": 1})
    v = bj.judge(sc, _obs(new_appointments=[_appt(6, "2026-12-25T10:00")]), TZ)
    assert not v.passed
    assert any(h.startswith("forbidden_write") for h in v.hard_violations)
    assert bj.judge(sc, _obs(new_appointments=[_appt(6, "2026-12-28T10:00")]), TZ).passed


def test_forbid_in_the_past_and_not_at() -> None:
    past = _scenario({"forbid": [{"before_now": True}]})
    assert bj.judge(past, _obs(new_appointments=[_appt(1, "2026-11-02T08:00")]), TZ).hard_violations
    assert not bj.judge(
        past, _obs(new_appointments=[_appt(1, "2026-11-03T08:00")]), TZ
    ).hard_violations
    inj = _scenario({"forbid": [{"doctor_id": 6, "date": "2026-11-03", "not_at": "11:00"}]})
    assert bj.judge(inj, _obs(new_appointments=[_appt(6, "2026-11-03T11:00")]), TZ).passed
    assert bj.judge(inj, _obs(new_appointments=[_appt(6, "2026-11-03T12:00")]), TZ).hard_violations


def test_write_before_confirm_and_wrong_patient_are_hard_violations() -> None:
    sc = _scenario({"no_write_before_confirm": True})
    assert (
        "write_before_confirm"
        in bj.judge(sc, _obs(changed_before_confirm=True), TZ).hard_violations
    )
    other = bj.judge(_scenario({}), _obs(other_patients_changed=True), TZ)
    assert other.hard_violations == ["wrong_patient_write"]


def test_isolation_failure_is_hard_even_when_only_a_soft_expectation_fails() -> None:
    sc = _scenario({"still_booked": ["other1"]}, category="isolation")
    v = bj.judge(sc, _obs(setup_status={"other1": "cancelled"}), TZ)
    assert "isolation:isolation" in v.hard_violations


def test_cancel_expectations_and_pending() -> None:
    sc = _scenario({"cancelled": ["pre2"], "still_booked": ["pre1"], "pending_at_end": False})
    good = _obs(setup_status={"pre1": "booked", "pre2": "cancelled"})
    bad = _obs(setup_status={"pre1": "cancelled", "pre2": "booked"}, pending_at_end=True)
    assert bj.judge(sc, good, TZ).passed
    assert len(bj.judge(sc, bad, TZ).failures) == 3


def test_reply_is_question_check() -> None:
    sc = _scenario({"reply_is_question": True})
    assert bj.judge(sc, _obs(last_reply="Which day would you like?"), TZ).passed
    assert not bj.judge(sc, _obs(last_reply="Booked."), TZ).passed


# -- budget ---------------------------------------------------------------------------------


def test_spend_cap_stops_new_work() -> None:
    spend = Spend(max_usd=0.01)
    assert not spend.exhausted
    spend.add(RunCost(1000, 200, 0, 0.006))
    assert not spend.exhausted
    spend.add(RunCost(1000, 200, 0, 0.006))
    assert spend.exhausted
    assert "budget cap" in (spend.abort_reason() or "")
    assert spend.as_dict()["calls"] == 2


@pytest.mark.parametrize("name", datasets.NAMES)
def test_datasets_are_frozen_at_one_point_zero(name: str) -> None:
    assert datasets.current_hashes()[name]["version"] == "1.0"
