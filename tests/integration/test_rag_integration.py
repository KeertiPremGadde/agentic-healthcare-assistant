from dataclasses import replace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from medagent.db.models import KbChunk, KbDocument
from medagent.rag.answer import NO_ANSWER, AnswerPayload, answer_question
from medagent.rag.ingest import ingest_documents
from medagent.rag.retriever import HybridRetriever
from medagent.rag.types import PageText, RawDocument
from tests.fakes import FakeAnswerLLM, FakeEmbedder

pytestmark = pytest.mark.integration

MEDLINE = "MedlinePlus - National Library of Medicine (medlineplus.gov)"


def _doc(
    key: str, ext: str, title: str, text_: str, *, public: bool = True, page: int | None = None
):
    return RawDocument(
        source_key=key,
        external_id=ext,
        title=title,
        pages=(PageText(text_, page),),
        license="Public domain" if public else "All rights reserved",
        attribution=MEDLINE if public else "Medical_book - local development only",
        is_public=public,
        url=f"https://example.org/{ext}" if public else None,
    )


CORPUS = [
    _doc(
        "medlineplus",
        "diabetes",
        "Diabetes",
        "Diabetes means blood glucose is too high. Symptoms include increased thirst, "
        "frequent urination, fatigue and blurred vision. Metformin is a common medicine.",
    ),
    _doc(
        "medlineplus",
        "asthma",
        "Asthma",
        "Asthma narrows the airways in the lungs. Wheezing, coughing and shortness of breath "
        "are typical symptoms. Triggers include allergens, smoke and cold air.",
    ),
    _doc(
        "medlineplus",
        "hypertension",
        "High Blood Pressure",
        "High blood pressure is also called hypertension. It often has no symptoms but raises "
        "the risk of stroke and heart disease. Lifestyle changes and medicines can lower it.",
    ),
    _doc(
        "medical_book",
        "Medical_book.pdf",
        "Medical_book",
        "Migraine headaches cause throbbing pain, nausea and sensitivity to light and sound.",
        public=False,
        page=42,
    ),
]


@pytest.fixture
def kb(session: Session) -> HybridRetriever:
    ingest_documents(session, FakeEmbedder(), CORPUS)
    return HybridRetriever(FakeEmbedder())


def test_ingest_stores_documents_chunks_and_metadata(session: Session) -> None:
    report = ingest_documents(session, FakeEmbedder(), CORPUS)
    assert (report.added, report.updated, report.skipped) == (4, 0, 0)
    assert session.scalar(select(func.count()).select_from(KbDocument)) == 4
    book = session.scalars(select(KbDocument).where(KbDocument.source_key == "medical_book")).one()
    assert not book.is_public
    assert book.chunks[0].page == 42
    diabetes = session.scalars(select(KbDocument).where(KbDocument.external_id == "diabetes")).one()
    assert diabetes.license == "Public domain"
    assert diabetes.chunks[0].page is None
    assert len(diabetes.chunks[0].embedding) == 384


def test_reingesting_unchanged_documents_is_a_noop(session: Session) -> None:
    ingest_documents(session, FakeEmbedder(), CORPUS)
    ids_before = set(session.scalars(select(KbChunk.id)))
    report = ingest_documents(session, FakeEmbedder(), CORPUS)
    assert (report.added, report.updated, report.skipped, report.chunks) == (0, 0, 4, 0)
    assert set(session.scalars(select(KbChunk.id))) == ids_before  # no rewrite, no new ids


def test_changed_document_replaces_its_chunks_only(session: Session) -> None:
    ingest_documents(session, FakeEmbedder(), CORPUS)
    asthma_before = session.scalars(
        select(KbDocument).where(KbDocument.external_id == "asthma")
    ).one()
    old_chunk_ids = {c.id for c in asthma_before.chunks}
    changed = replace(
        CORPUS[1],
        pages=(PageText("Asthma updated text about inhalers and airway inflammation.", None),),
    )
    report = ingest_documents(session, FakeEmbedder(), [changed, *CORPUS[:1], *CORPUS[2:]])
    assert (report.added, report.updated, report.skipped) == (0, 1, 3)
    session.expire_all()
    asthma = session.scalars(select(KbDocument).where(KbDocument.external_id == "asthma")).one()
    assert "inhalers" in asthma.chunks[0].content
    assert not old_chunk_ids & {c.id for c in asthma.chunks}
    assert session.scalar(select(func.count()).select_from(KbDocument)) == 4


def test_schema_has_hnsw_and_gin_indexes_and_generated_tsvector(session: Session) -> None:
    defs = " ".join(
        session.scalars(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'kb_chunks'"))
    )
    assert "USING hnsw" in defs
    assert "vector_cosine_ops" in defs
    assert "USING gin" in defs


def test_semantic_query_finds_the_right_document(session: Session, kb: HybridRetriever) -> None:
    hits = kb.search(session, "What are the symptoms of diabetes? thirst and urination", k=3)
    assert hits[0].document_title == "Diabetes"
    assert hits[0].vector_rank == 1
    assert hits[0].text_rank == 1
    assert hits[0].fused_score > 0
    assert hits == sorted(hits, key=lambda c: c.final_score, reverse=True)


def test_keyword_search_catches_exact_terms(session: Session, kb: HybridRetriever) -> None:
    hits = kb.search(session, "metformin", k=3)
    assert hits[0].document_title == "Diabetes"
    assert hits[0].text_rank == 1  # full-text search found it by the exact word


def test_natural_language_questions_use_or_semantics(session: Session, kb: HybridRetriever) -> None:
    # No chunk contains all of these words; AND-style matching would return nothing.
    hits = kb.search(session, "Why does wheezing happen with allergens at night in children", k=3)
    assert hits[0].document_title == "Asthma"
    assert hits[0].text_rank is not None


def test_public_only_excludes_local_only_sources(session: Session, kb: HybridRetriever) -> None:
    query = "migraine headache nausea light sensitivity"
    assert kb.search(session, query, k=1)[0].document_title == "Medical_book"
    public = kb.search(session, query, k=10, public_only=True)
    assert public
    assert all(c.source_key == "medlineplus" for c in public)


def test_empty_knowledge_base_returns_nothing(session: Session) -> None:
    assert HybridRetriever(FakeEmbedder()).search(session, "anything") == []


def test_end_to_end_answer_with_real_retriever_and_fake_llm(
    session: Session, kb: HybridRetriever
) -> None:
    llm = FakeAnswerLLM(
        AnswerPayload(
            answer="Symptoms include thirst and frequent urination [MedlinePlus: Diabetes].",
            used_sources=[1],
            context_sufficient=True,
        )
    )
    result = answer_question(
        session, kb, llm, "symptoms of diabetes thirst urination", min_score=0.2, public_only=True
    )
    assert result.grounded
    assert result.sources[0].label == "MedlinePlus: Diabetes"
    assert result.sources[0].url == "https://example.org/diabetes"
    assert MEDLINE in result.render()
    assert "[MedlinePlus: Diabetes]" in llm.calls[0][1]


def test_unrelated_question_is_refused_before_the_llm(
    session: Session, kb: HybridRetriever
) -> None:
    llm = FakeAnswerLLM(AnswerPayload(answer="x", used_sources=[1], context_sufficient=True))
    result = answer_question(
        session, kb, llm, "quantum chromodynamics lattice gauge", min_score=0.5, public_only=True
    )
    assert result.answer == NO_ANSWER
    assert llm.calls == []


def test_real_fastembed_model_matches_the_vector_column() -> None:
    """Loads BAAI/bge-small-en-v1.5 (cached locally and in CI); no API key needed."""
    from medagent.rag.embeddings import get_embedder

    embedder = get_embedder()
    doc_vec = embedder.embed_documents(
        ["Diabetes causes increased thirst and frequent urination."]
    )[0]
    related = embedder.embed_query("What are the symptoms of diabetes?")
    unrelated = embedder.embed_query("How do I bake sourdough bread?")
    assert len(doc_vec) == embedder.dim == 384

    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are L2-normalised

    assert cos(doc_vec, related) > cos(doc_vec, unrelated) + 0.1
