"""One real Claude call (a few hundred tokens). Run with: uv run pytest -m llm"""

import pytest
from sqlalchemy.orm import Session

from medagent.core.config import get_settings
from medagent.rag.answer import AnthropicAnswerLLM, answer_question
from medagent.rag.ingest import ingest_documents
from medagent.rag.retriever import HybridRetriever
from tests.fakes import FakeEmbedder
from tests.integration.test_rag_integration import CORPUS

pytestmark = [pytest.mark.integration, pytest.mark.llm]


def test_claude_answers_from_context_with_citations(session: Session) -> None:
    if get_settings().anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    ingest_documents(session, FakeEmbedder(), CORPUS)
    result = answer_question(
        session,
        HybridRetriever(FakeEmbedder()),
        AnthropicAnswerLLM(),
        "What are the symptoms of diabetes?",
        min_score=0.2,
        public_only=True,
    )
    assert result.grounded
    assert "thirst" in result.answer.lower()
    assert any(s.label == "MedlinePlus: Diabetes" for s in result.sources)
    assert "[MedlinePlus: Diabetes]" in result.answer


def test_claude_refuses_when_context_does_not_cover_the_question(session: Session) -> None:
    if get_settings().anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    ingest_documents(session, FakeEmbedder(), CORPUS)
    result = answer_question(
        session,
        HybridRetriever(FakeEmbedder()),
        AnthropicAnswerLLM(),
        "What is the recommended insulin dose for a child with diabetes?",
        min_score=0.0,  # force the LLM to judge; the corpus has no dosing info
        public_only=True,
    )
    assert not result.grounded
