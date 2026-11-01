"""Plain data types shared by the RAG pipeline (no DB, no LLM)."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PageText:
    """Text of one page (PDF) or the whole document (page=None for web/XML sources)."""

    text: str
    page: int | None = None


@dataclass(frozen=True, slots=True)
class RawDocument:
    """A source document before chunking, with the licence info needed for citations."""

    source_key: str  # e.g. "medlineplus", "medical_book"
    external_id: str  # stable id within the source (topic id, file name)
    title: str
    pages: tuple[PageText, ...]
    license: str
    attribution: str
    is_public: bool  # False = local dev only; excluded when KB_PUBLIC_ONLY=true
    url: str | None = None
    synonyms: tuple[str, ...] = ()  # "Also called" names, used in the chunk header


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    text: str
    page: int | None


@dataclass(slots=True)
class Candidate:
    """A retrieved chunk plus the scores the retriever and reranker work with."""

    chunk_id: int
    content: str
    document_title: str
    source_key: str
    url: str | None
    attribution: str
    page: int | None
    vector_sim: float  # cosine similarity in [-1, 1]; the signal used to decide "I don't know"
    vector_rank: int | None = None  # 1-based rank in the vector list, None if absent
    text_rank: int | None = None  # 1-based rank in the full-text list, None if absent
    fused_score: float = 0.0  # reciprocal-rank-fusion score
    final_score: float = field(default=0.0)  # set by the reranker

    @property
    def citation(self) -> str:
        """`[Medical_book p.12]` for paged sources, `[MedlinePlus: Diabetes]` otherwise."""
        if self.page is not None:
            return f"[{self.document_title} p.{self.page}]"
        return f"[{self.attribution_label}: {self.document_title}]"

    @property
    def attribution_label(self) -> str:
        return self.attribution.split(" - ")[0]
