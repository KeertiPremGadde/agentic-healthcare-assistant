"""Split documents into overlapping chunks that keep their page number.

Sized in characters because the embedder (bge-small) truncates input at 512 tokens:
~1200 characters is roughly 300 tokens, comfortably inside that limit.
"""

from collections.abc import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from medagent.rag.types import Chunk, PageText

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 40  # drop page numbers, headers and other noise


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
