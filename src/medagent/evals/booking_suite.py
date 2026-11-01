"""Booking and cancelling scenarios, run end to end through the graph on a throwaway database.

A fresh `<db>_evals` database is built with the real migrations and the seed, a fixed clock is
injected, and every scenario starts from the same state (its own setup appointments only). The
verdict comes from the database after the run (`booking_judge`), never from the reply text.
"""

import os
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import build_graph
from medagent.agents.llm import AnthropicStructuredLLM
from medagent.agents.runner import TurnResult, run_turn
from medagent.core.config import get_settings
from medagent.db import repository
from medagent.db.models import Appointment, Doctor
from medagent.db.seed import seed
from medagent.evals import booking_judge, datasets
from medagent.evals.results import EvalResult, Spend, git_sha, new_run_id
from medagent.rag.answer import AnswerPayload
from medagent.rag.types import Candidate
from medagent.tools.clinic import ClinicService, LocalClinicTools

OTHER_PATIENT = "sam.sample@example.com"


class _NoRetrieval:
    """Booking scenarios never use the knowledge base."""

    def search(
        self, session: Session, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]:
        return []


class _NoAnswer:
    def generate(self, question: str, system_prompt: str) -> AnswerPayload:
        return AnswerPayload(answer="", used_sources=[], context_sufficient=False)


@contextmanager
def throwaway_database() -> Iterator[Engine]:
    """Create `<db>_evals`, migrate and seed it; drop it afterwards."""
    base = make_url(get_settings().database_url)
    name = f"{base.database}_evals"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # alembic's env.py reads the URL from settings
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        with Session(engine) as session:
            seed(session)
            session.commit()
        yield engine
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


Snapshot = dict[int, tuple[int, int, datetime, str]]  # id -> patient, doctor, start, status


def _snapshot(session: Session) -> Snapshot:
    session.expire_all()
    rows = session.scalars(select(Appointment)).all()
    return {a.id: (a.patient_id, a.doctor_id, a.start_time, str(a.status)) for a in rows}


@dataclass
class ScenarioRun:
    scenario_id: str
    category: str
    passed: bool
    failures: list[str]
    hard_violations: list[str]
    replies: list[str]
    cost_usd: float


async def _run_scenario(
    sc: datasets.Scenario,
    sessions: sessionmaker[Session],
    graph: object,
    patients: dict[str, int],
    now: datetime,
    tz: ZoneInfo,
    spend: Spend,
) -> ScenarioRun:
    with sessions() as session:
        session.execute(delete(Appointment))
        session.commit()
        refs: dict[str, int] = {}
        for a in sc.setup:
            start = datetime.fromisoformat(a.start).replace(tzinfo=tz).astimezone(UTC)
            refs[a.ref] = repository.create_appointment(
                session, patients[a.patient], a.doctor_id, start
            ).id
        baseline = _snapshot(session)

    alex = patients["alex"]
    thread = f"eval-{sc.id}-{uuid.uuid4().hex[:6]}"
    pending = False
    changed_before_confirm = False
    replies: list[str] = []
    cost = 0.0
    failures: list[str] = []

    async def send(**kwargs: object) -> TurnResult:
        nonlocal pending, changed_before_confirm, cost
        result = await run_turn(graph, thread, alex, **kwargs)  # type: ignore[arg-type]
        spend.add(result.cost)
        cost += result.cost.usd
        pending = result.pending is not None
        if result.reply:
            replies.append(result.reply)
        if pending:  # the graph paused: nothing may have been written yet
            with sessions() as s:
                if _snapshot(s) != baseline:
                    changed_before_confirm = True
        return result

    for turn in sc.turns:
        if turn.user is not None:
            await send(message=turn.user)
        elif turn.confirm is not None:
            if not pending:
                failures.append("confirm_without_pending")
                continue
            await send(resume=turn.confirm)
        elif turn.confirm_if_pending and pending:
            await send(resume=True)

    with sessions() as session:
        after = _snapshot(session)
        doctors = {d.id: d.specialty for d in session.scalars(select(Doctor))}
    by_alex = {i: v for i, v in after.items() if v[0] == alex}
    new = [
        booking_judge.Appt(i, "alex", v[1], str(doctors[v[1]]), v[2], v[3])
        for i, v in by_alex.items()
        if i not in baseline
    ]
    others_before = {i: v for i, v in baseline.items() if v[0] != alex}
    others_after = {i: v for i, v in after.items() if v[0] != alex}
    obs = booking_judge.Observation(
        new_appointments=new,
        setup_status={ref: after[i][3] if i in after else "deleted" for ref, i in refs.items()},
        other_patients_changed=others_before != others_after,
        changed_before_confirm=changed_before_confirm,
        pending_at_end=pending,
        last_reply=replies[-1] if replies else None,
        now=now,
    )
    verdict = booking_judge.judge(sc, obs, tz)
    verdict.failures.extend(failures)
    return ScenarioRun(
        sc.id,
        sc.category,
        verdict.passed and not failures,
        verdict.failures,
        verdict.hard_violations,
        replies,
        round(cost, 5),
    )


async def run_booking(spend: Spend, only: Sequence[str] | None = None) -> EvalResult:
    settings = get_settings()
    data, meta = datasets.load_booking()
    scenarios = [s for s in data.items if only is None or s.id in only]
    now = datetime.fromisoformat(meta["clock"]).astimezone(UTC)
    tz = ZoneInfo(settings.clinic_timezone)
    result = EvalResult(
        suite="booking",
        run_id=new_run_id("booking"),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        model=settings.llm_model,
        datasets={"booking_scenarios": datasets.current_hashes()["booking_scenarios"]},
        params={"scenarios": len(scenarios), "clock": meta["clock"]},
        metrics={},
    )
    runs: list[ScenarioRun] = []
    with throwaway_database() as engine:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as s:
            patients = {
                "alex": repository.get_patient_by_email(s, meta["patient"]).id,  # type: ignore[union-attr]
                "other": repository.get_patient_by_email(s, OTHER_PATIENT).id,  # type: ignore[union-attr]
            }
        deps = AgentDeps(
            tools=LocalClinicTools(ClinicService(sessions, lambda: now, tz, settings.slot_minutes)),
            llm=AnthropicStructuredLLM(settings),
            answer_llm=_NoAnswer(),
            retriever=_NoRetrieval(),
            session_factory=sessions,
            clock=lambda: now,
            tz=tz,
            public_only=True,
            rag_min_score=settings.rag_min_score,
        )
        graph = build_graph(deps, InMemorySaver())
        for sc in scenarios:
            if spend.exhausted:
                break
            runs.append(await _run_scenario(sc, sessions, graph, patients, now, tz, spend))

    n = len(runs)
    passed = sum(r.passed for r in runs)
    hard = [f"{r.scenario_id}:{v}" for r in runs for v in r.hard_violations]
    result.metrics = {
        "task_success": round(passed / n, 4) if n else None,
        "scenarios_run": n,
        "hard_violation_count": len(hard),
        "by_category": {
            c: round(
                sum(r.passed for r in runs if r.category == c)
                / sum(1 for r in runs if r.category == c),
                4,
            )
            for c in sorted({r.category for r in runs})
        },
    }
    result.hard_violations = hard
    result.aborted = spend.abort_reason()
    result.cost = spend.as_dict()
    result.items = [
        {
            "id": r.scenario_id,
            "category": r.category,
            "passed": r.passed,
            "failures": r.failures,
            "hard_violations": r.hard_violations,
            "replies": r.replies,
            "cost_usd": r.cost_usd,
        }
        for r in runs
    ]
    return result
