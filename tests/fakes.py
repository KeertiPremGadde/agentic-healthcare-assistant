"""Test doubles: a deterministic offline embedder and a scripted answer LLM."""

import asyncio
import hashlib
import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from medagent.db.models import EMBEDDING_DIM
from medagent.integrations.calendar import CalendarEvent, event_id_for
from medagent.rag.answer import AnswerPayload
from medagent.rag.types import Candidate

T = TypeVar("T", bound=BaseModel)

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
    ]
)


class FakeEmbedder:
    """Content-word hashing embedder: texts sharing words get similar vectors, no model needed."""

    dim = EMBEDDING_DIM

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            if word in _STOPWORDS:
                continue
            bucket = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16)
            vec[bucket % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeAnswerLLM:
    """Returns a scripted payload and records the prompts it was given."""

    def __init__(self, payload: AnswerPayload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def generate(self, question: str, system_prompt: str) -> AnswerPayload:
        self.calls.append((question, system_prompt))
        return self.payload


class FakeStructuredLLM:
    """Scripted structured outputs, queued per schema. An unscripted call fails the test, which
    is how tests prove that e.g. an emergency never reaches the LLM. Exceptions in the queue are
    raised instead of returned (to simulate API failures)."""

    def __init__(
        self,
        script: dict[type[BaseModel], list[BaseModel | Exception]] | None = None,
        delay: float = 0.0,
    ):
        self.delay = delay  # seconds each call takes (to simulate a slow model)
        self.script: dict[type[BaseModel], list[BaseModel | Exception]] = {
            k: list(v) for k, v in (script or {}).items()
        }
        self.calls: list[tuple[type[BaseModel], str, list[BaseMessage]]] = []

    def push(self, *outputs: BaseModel) -> None:
        for output in outputs:
            self.script.setdefault(type(output), []).append(output)

    async def ainvoke(self, schema: type[T], system: str, messages: Sequence[BaseMessage]) -> T:
        self.calls.append((schema, system, list(messages)))
        if self.delay:
            await asyncio.sleep(self.delay)
        queue = self.script.get(schema)
        if not queue:
            raise AssertionError(f"unexpected LLM call for {schema.__name__}")
        output = queue.pop(0)
        if isinstance(output, Exception):
            raise output
        assert isinstance(output, schema)
        return output

    @property
    def schemas_called(self) -> list[str]:
        return [schema.__name__ for schema, _, _ in self.calls]


class FakeRetriever:
    def __init__(self, candidates: list[Candidate] | None = None) -> None:
        self.candidates = candidates or []

    def search(
        self, session: Session, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]:
        return self.candidates[:k]


@contextmanager
def no_database() -> Iterator[Session]:
    raise AssertionError("this test must not touch the database")
    yield  # pragma: no cover


class FakeCalendar:
    """Records calendar calls; can be told to fail, to test the best-effort behaviour."""

    enabled = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.added: list[int] = []
        self.removed: list[int] = []

    def add(self, event: "CalendarEvent") -> str | None:
        if self.fail:
            raise ConnectionError("calendar down")
        self.added.append(event.appointment_id)
        return event_id_for(event.appointment_id)

    def remove(self, appointment_id: int) -> bool:
        if self.fail:
            raise ConnectionError("calendar down")
        self.removed.append(appointment_id)
        return True


class NoTools:
    """Tools for graph tests that must not touch scheduling: any call fails the test."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected tool call: {name}")
