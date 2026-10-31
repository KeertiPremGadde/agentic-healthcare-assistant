"""Hybrid retrieval: vector search + Postgres full-text search, fused with reciprocal-rank
fusion (RRF), then reranked.

Why hybrid: embeddings catch paraphrases ("high blood pressure" ~ "hypertension"), full-text
catches exact terms (drug names, acronyms). Why RRF: the two scores live on different scales,
but ranks are comparable, so we fuse ranks instead of scores.
"""

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from medagent.rag.embeddings import Embedder
from medagent.rag.types import Candidate

RRF_K = 60  # standard constant from the original RRF paper: dampens the top ranks' dominance
CANDIDATES_PER_LIST = 20


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    """score(id) = sum over lists of 1 / (k + rank), rank starting at 1. Pure."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]: ...


class ScoreReranker:
    """Cheap, deterministic reranker: blends semantic similarity with the fused rank signal.

    final = w * cosine_similarity + (1 - w) * (fused / best_possible_fused)

    A cross-encoder (reads query and passage together) is the later upgrade: more accurate,
    but a heavier model to ship. It would implement the same `Reranker` interface.
    """

    def __init__(self, similarity_weight: float = 0.6, rrf_k: int = RRF_K) -> None:
        self.w = similarity_weight
        self.best_fused = 2.0 / (rrf_k + 1)  # rank 1 in both lists

    def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]:
        for c in candidates:
            c.final_score = self.w * c.vector_sim + (1 - self.w) * (c.fused_score / self.best_fused)
        return sorted(candidates, key=lambda c: c.final_score, reverse=True)


_COLUMNS = """
    c.id, c.content, c.page, d.title, d.source_key, d.url, d.attribution,
    1 - (c.embedding <=> CAST(:qvec AS vector)) AS sim
"""
_FROM = "FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id"

_VECTOR_SQL = text(
    f"SELECT {_COLUMNS} {_FROM} "
    "WHERE (:public_only IS FALSE OR d.is_public) "
    "ORDER BY c.embedding <=> CAST(:qvec AS vector) LIMIT :n"
)
# OR-semantics keyword query: a natural-language question rarely contains every word of a chunk.
_TEXT_SQL = text(
    f"SELECT {_COLUMNS}, ts_rank_cd(c.tsv, q.query) AS rank {_FROM}, "
    "LATERAL (SELECT replace(plainto_tsquery('english', :q)::text, '&', '|')::tsquery AS query) q "
    "WHERE c.tsv @@ q.query AND (:public_only IS FALSE OR d.is_public) "
    "ORDER BY rank DESC LIMIT :n"
)


class HybridRetriever:
    def __init__(
        self,
        embedder: Embedder,
        reranker: Reranker | None = None,
        candidates_per_list: int = CANDIDATES_PER_LIST,
    ) -> None:
        self.embedder = embedder
        self.reranker = reranker or ScoreReranker()
        self.n = candidates_per_list

    def search(
        self, session: Session, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]:
        qvec = str(self.embedder.embed_query(query))  # pgvector accepts '[0.1, 0.2, ...]'
        params = {"qvec": qvec, "q": query, "n": self.n, "public_only": public_only}
        vector_rows = session.execute(_VECTOR_SQL, params).all()
        text_rows = session.execute(_TEXT_SQL, params).all()

        by_id: dict[int, Candidate] = {}
        for rank, row in enumerate(vector_rows, start=1):
            by_id[row.id] = _to_candidate(row)
            by_id[row.id].vector_rank = rank
        for rank, row in enumerate(text_rows, start=1):
            by_id.setdefault(row.id, _to_candidate(row)).text_rank = rank

        fused = reciprocal_rank_fusion(
            [[r.id for r in vector_rows], [r.id for r in text_rows]],
        )
        for chunk_id, score in fused.items():
            by_id[chunk_id].fused_score = score
        ranked = self.reranker.rerank(query, list(by_id.values()))
        return ranked[:k]


def _to_candidate(row: object) -> Candidate:
    return Candidate(
        chunk_id=row.id,  # type: ignore[attr-defined]
        content=row.content,  # type: ignore[attr-defined]
        document_title=row.title,  # type: ignore[attr-defined]
        source_key=row.source_key,  # type: ignore[attr-defined]
        url=row.url,  # type: ignore[attr-defined]
        attribution=row.attribution,  # type: ignore[attr-defined]
        page=row.page,  # type: ignore[attr-defined]
        vector_sim=float(row.sim),  # type: ignore[attr-defined]
    )
