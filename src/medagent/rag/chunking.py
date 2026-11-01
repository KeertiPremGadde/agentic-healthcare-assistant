"""Split documents into overlapping chunks that keep their page number.

Sized in characters because the embedder (bge-small) truncates input at 512 tokens:
~1200 characters is roughly 300 tokens, comfortably inside that limit.
"""

from collections.abc import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from medagent.rag.types import Chunk, PageText, RawDocument

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 40  # drop page numbers, headers and other noise


def context_header(doc: RawDocument) -> str:
    """One line naming the topic, prepended to every chunk before embedding and full-text indexing.

    A mid-topic chunk says nothing about which topic it belongs to ("symptoms of diabetes" then
    matches a risk-factors chunk of another page). Paged sources (PDF titles are file names): none.
    """
    if any(p.page is not None for p in doc.pages):
        return ""
    if doc.synonyms:
        return f"{doc.title} (also called: {', '.join(doc.synonyms)})"
    return doc.title


def chunk_pages(
    pages: Iterable[PageText], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    """Chunk page by page (so every chunk has exactly one page for citations)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[Chunk] = []
    for page in pages:
        for piece in splitter.split_text(page.text):
            text = piece.strip()
            if len(text) >= MIN_CHUNK_CHARS:
                chunks.append(Chunk(index=len(chunks), text=text, page=page.page))
    return chunks
