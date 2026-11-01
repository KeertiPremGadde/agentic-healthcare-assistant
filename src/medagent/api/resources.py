"""Everything the API shares between requests, built once at start-up (FastAPI lifespan).

Tests build a `Resources` directly with a fake LLM, in-memory checkpointer and local tools.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from medagent.agents.checkpointer import postgres_checkpointer_pool
from medagent.agents.deps import default_deps, open_tools
from medagent.agents.graph import AgentGraph, build_graph
from medagent.api.accounts import SessionFactory
from medagent.api.limits import ConversationLocks, RateLimiter, UsageStore
from medagent.core.config import Settings
from medagent.observability.tracing import NullTracer, Tracer, get_tracer
from medagent.tools.clinic import ClinicTools


@dataclass
class Resources:
    settings: Settings
    graph: AgentGraph
    clinic: ClinicTools  # REST endpoints (appointments) use the same service, in-process
    session_factory: SessionFactory
    usage: UsageStore
    limiter: RateLimiter
    locks: ConversationLocks
    tracer: Tracer = field(default_factory=NullTracer)  # Langfuse when configured


@asynccontextmanager
async def open_resources(settings: Settings) -> AsyncIterator[Resources]:
    """The real thing: MCP session, pooled Postgres checkpointer, Anthropic, local embeddings."""
    from medagent.db.session import get_sessionmaker
    from medagent.mcp_server.server import default_service
    from medagent.tools.clinic import LocalClinicTools

    tracer = get_tracer(settings)
    try:
        async with open_tools(settings) as tools, postgres_checkpointer_pool() as saver:
            graph = build_graph(default_deps(tools, settings), saver)
            session_factory = get_sessionmaker()
            yield Resources(
                settings=settings,
                graph=graph,
                clinic=LocalClinicTools(default_service()),
                session_factory=session_factory,
                usage=UsageStore(session_factory),
                limiter=RateLimiter(),
                locks=ConversationLocks(),
                tracer=tracer,
            )
    finally:
        tracer.shutdown()  # send anything still queued
