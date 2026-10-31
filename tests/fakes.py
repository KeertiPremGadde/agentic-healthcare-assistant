"""Test doubles: a deterministic offline embedder and a scripted answer LLM."""

import hashlib
import math
import re
from collections.abc import Sequence

from medagent.db.models import EMBEDDING_DIM
from medagent.rag.answer import AnswerPayload

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
