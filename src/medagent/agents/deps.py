"""Everything the nodes need from the outside world, injected once when the graph is built.

Tests swap in a fake LLM, a fixed clock and a test database without touching node code.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from medagent.agents.llm import StructuredLLM
from medagent.core.config import Settings, get_settings
from medagent.rag.answer import AnswerLLM, Retriever


@dataclass(frozen=True)
class AgentDeps:
    session_factory: Callable[[], AbstractContextManager[Session]]
    llm: StructuredLLM  # routing + extraction (low effort)
    answer_llm: AnswerLLM  # cited medical answers
    retriever: Retriever
    clock: Callable[[], datetime]
    tz: ZoneInfo
    slot_minutes: int
    public_only: bool
    rag_min_score: float


def default_deps(settings: Settings | None = None) -> AgentDeps:
    """Real dependencies: Postgres, Anthropic, local embeddings."""
    from medagent.agents.llm import AnthropicStructuredLLM
    from medagent.db.session import get_sessionmaker
    from medagent.rag.answer import AnthropicAnswerLLM
    from medagent.rag.embeddings import get_embedder
    from medagent.rag.retriever import HybridRetriever

    settings = settings or get_settings()
    return AgentDeps(
        session_factory=get_sessionmaker(),
        llm=AnthropicStructuredLLM(settings),
        answer_llm=AnthropicAnswerLLM(settings),
        retriever=HybridRetriever(get_embedder(settings)),
        clock=lambda: datetime.now(UTC),
        tz=ZoneInfo(settings.clinic_timezone),
        slot_minutes=settings.slot_minutes,
        public_only=settings.kb_public_only,
        rag_min_score=settings.rag_min_score,
    )
