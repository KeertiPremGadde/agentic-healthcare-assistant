"""Typed loaders for the frozen golden sets in `evals/datasets/`.

A lock file (`datasets.lock.json`) holds the SHA-256 of each file, so a result file can say
exactly which data it was measured on and a test fails if a dataset changes without a new
version and a new lock.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from medagent.agents.schemas import Route

DATASET_DIR = Path(__file__).resolve().parents[3] / "evals" / "datasets"
LOCK_FILE = DATASET_DIR / "datasets.lock.json"
NAMES = ("rag_golden", "routing_golden", "booking_scenarios", "threshold_dev", "redteam_e2e")

RagKind = Literal["in_scope", "in_scope_de", "near_miss", "off_topic"]


class RagQuestion(BaseModel):
    id: str
    kind: RagKind
    source: str
    question: str
    expected_topics: list[str] = Field(default_factory=list)
    reference: str | None = None
    expect: Literal["abstain", "refer", "redirect"] | None = None
    hard_negative: bool = False
    note: str | None = None


class RoutingMessage(BaseModel):
    id: str
    route: Route
    text: str
    emergency: bool = False
    harmful: bool = False
    accept: list[Route] = Field(default_factory=list)


class Turn(BaseModel):
    user: str | None = None
    confirm: bool | None = None
    confirm_if_pending: bool | None = None


class SetupAppointment(BaseModel):
    ref: str
    patient: Literal["alex", "other"] = "alex"
    doctor_id: int
    start: str  # local clinic time, "YYYY-MM-DDTHH:MM"


class Match(BaseModel):
    """A new appointment (or a forbidden one): doctor or specialty, local date, time rule."""

    doctor_id: int | None = None
    specialty: str | None = None
    date: str | None = None
    at: str | None = None
    not_at: str | None = None
    between: tuple[str, str] | None = None
    before_now: bool = False


class Expect(BaseModel):
    no_write_before_confirm: bool = False
    bookings: list[Match] | None = None  # exactly these new appointments, nothing else
    bookings_at_most: int | None = None
    forbid: list[Match] = Field(default_factory=list)
    cancelled: list[str] = Field(default_factory=list)
    still_booked: list[str] = Field(default_factory=list)
    pending_at_end: bool | None = None
    reply_is_question: bool = False


class Scenario(BaseModel):
    id: str
    category: str
    note: str | None = None
    setup: list[SetupAppointment] = Field(default_factory=list)
    turns: list[Turn]
    expect: Expect


class Dataset[T](BaseModel):
    version: str
    items: list[T]
    sha256: str


def _read(name: str) -> tuple[dict[str, object], str]:
    raw = (DATASET_DIR / f"{name}.json").read_bytes()
    # Hash the parsed content, not the bytes, so line endings (CRLF/LF) cannot change it.
    data: dict[str, object] = json.loads(raw)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return data, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_hashes() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name in NAMES:
        data, digest = _read(name)
        out[name] = {"version": str(data["version"]), "sha256": digest}
    return out


def load_rag() -> Dataset[RagQuestion]:
    data, digest = _read("rag_golden")
    items = [RagQuestion.model_validate(q) for q in data["questions"]]  # type: ignore[attr-defined]
    return Dataset(version=str(data["version"]), items=items, sha256=digest)


def load_threshold_dev() -> Dataset[RagQuestion]:
    """The RAG_MIN_SCORE tuning set: same schema as the golden set, never part of its score."""
    data, digest = _read("threshold_dev")
    items = [RagQuestion.model_validate(q) for q in data["questions"]]  # type: ignore[attr-defined]
    return Dataset(version=str(data["version"]), items=items, sha256=digest)


ORIGINAL_REDTEAM = DATASET_DIR.parent / "redteam" / "cases.json"
_ORIGINAL_EXPECT = {
    "harmful": "block_safety",
    "emergency": "block_emergency",
    "dose": "no_dose",
    "allow": "allow",
    "llm": "safe_shape",
}


def load_redteam() -> Dataset[dict[str, object]]:
    """The red-team cases: the original 50 (hard gates, `source: orig`) then the new ones.

    The version and hash are those of the new cases' file (`redteam_e2e.json`); the original
    file is the one the rule-level unit tests also read."""
    data, digest = _read("redteam_e2e")
    original = json.loads(ORIGINAL_REDTEAM.read_text(encoding="utf-8"))["cases"]
    cases: list[dict[str, object]] = [
        {
            "id": c["id"],
            "group": "original",
            "expect": _ORIGINAL_EXPECT[c["expect"]],
            "lang": "mixed",
            "turns": [c["text"]],
            "note": c.get("note", ""),
            "source": "orig",
            "split": "orig",
        }
        for c in original
    ]
    cases += data["cases"]  # type: ignore[arg-type]
    return Dataset(version=str(data["version"]), items=cases, sha256=digest)


def load_routing() -> Dataset[RoutingMessage]:
    data, digest = _read("routing_golden")
    items = [RoutingMessage.model_validate(m) for m in data["messages"]]  # type: ignore[attr-defined]
    return Dataset(version=str(data["version"]), items=items, sha256=digest)


def load_booking() -> tuple[Dataset[Scenario], dict[str, str]]:
    """The scenarios plus the run settings (fixed clock, patient)."""
    data, digest = _read("booking_scenarios")
    raw = data["scenarios"]
    items = []
    for s in raw:  # type: ignore[attr-defined]
        s = dict(s)
        s["setup"] = (s.get("setup") or {}).get("appointments", [])
        items.append(Scenario.model_validate(s))
    meta = {"clock": str(data["clock"]), "patient": str(data["patient"])}
    return Dataset(version=str(data["version"]), items=items, sha256=digest), meta
