"""Everything the nodes need from the outside world, injected once when the graph is built.

Tests swap in a fake LLM, a fixed clock, local tools and a test database without touching nodes.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from medagent.agents.llm import StructuredLLM
from medagent.core.config import Settings, get_settings
from medagent.rag.answer import AnswerLLM, Retriever
from medagent.tools.clinic import ClinicTools


@dataclass(frozen=True)
class AgentDeps:
    tools: ClinicTools  # doctors, availability, booking, cancelling, nearby clinics
    llm: StructuredLLM  # routing + extraction (low effort)
    answer_llm: AnswerLLM  # cited medical answers
    retriever: Retriever
    session_factory: Callable[[], AbstractContextManager[Session]]  # RAG retrieval only
    clock: Callable[[], datetime]
    tz: ZoneInfo
    public_only: bool
    rag_min_score: float


@asynccontextmanager
async def open_tools(settings: Settings | None = None) -> AsyncIterator[ClinicTools]:
    """The configured tools: the MCP server over stdio (default) or in-process."""
    settings = settings or get_settings()
    if settings.tools_transport == "mcp":
        from medagent.tools.mcp_client import MCPClinicTools

        async with MCPClinicTools(settings) as mcp_tools:
            yield mcp_tools
        return
    from medagent.mcp_server.server import default_service
    from medagent.tools.clinic import LocalClinicTools

    yield LocalClinicTools(default_service())


def default_deps(tools: ClinicTools, settings: Settings | None = None) -> AgentDeps:
    """Real dependencies: Anthropic, local embeddings, Postgres, and the given tools."""
    from medagent.agents.llm import AnthropicStructuredLLM
    from medagent.db.session import get_sessionmaker
    from medagent.rag.answer import AnthropicAnswerLLM
    from medagent.rag.embeddings import get_embedder
    from medagent.rag.retriever import HybridRetriever

    settings = settings or get_settings()
    return AgentDeps(
        tools=tools,
        llm=AnthropicStructuredLLM(settings),
        answer_llm=AnthropicAnswerLLM(settings),
        retriever=HybridRetriever(get_embedder(settings)),
        session_factory=get_sessionmaker(),
        clock=lambda: datetime.now(UTC),
        tz=ZoneInfo(settings.clinic_timezone),
        public_only=settings.kb_public_only,
        rag_min_score=settings.rag_min_score,
    )
