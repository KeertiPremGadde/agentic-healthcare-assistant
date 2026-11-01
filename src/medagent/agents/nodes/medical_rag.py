"""Medical question -> Phase 2 RAG pipeline (cited answer or "I don't know")."""

import asyncio
from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.nodes.common import APOLOGY, Node, last_user_text
from medagent.agents.state import AgentState
from medagent.rag.answer import RagAnswer, answer_question

log = structlog.get_logger("medagent.agents")


def make_medical_rag_node(deps: AgentDeps) -> Node:
    def answer(question: str, search_query: str | None, language: str) -> RagAnswer:
        with deps.session_factory() as session:
            return answer_question(
                session,
                deps.retriever,
                deps.answer_llm,
                question,
                min_score=deps.rag_min_score,
                public_only=deps.public_only,
                search_query=search_query,
                language=language,
            )

    async def medical_rag_node(state: AgentState) -> dict[str, Any]:
        try:
            # The RAG pipeline is sync (SQLAlchemy + embeddings): keep the event loop free.
            result = await asyncio.to_thread(
                answer,
                last_user_text(state),
                state.get("search_query_en") or None,
                state.get("reply_language") or "en",
            )
        except Exception as exc:  # LLM or DB failure: apologise rather than crash the chat
            log.warning("node_failed", node="medical_rag", error=type(exc).__name__)
            return {"draft": APOLOGY, "draft_kind": "info"}
        return {"draft": result.render(), "draft_kind": "medical"}

    return medical_rag_node
