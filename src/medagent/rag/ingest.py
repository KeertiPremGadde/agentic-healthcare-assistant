"""Ingestion: loader -> chunk -> embed -> pgvector. Idempotent and source-agnostic.

    uv run python -m medagent.rag.ingest medlineplus [--limit N]
    uv run python -m medagent.rag.ingest medical_book      # local dev only, never public

A document whose text hash is unchanged is skipped (no embedding cost); a changed one has its
chunks replaced in one transaction, so the knowledge base is never left half-updated.
"""

import argparse
import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from medagent.db.models import KbChunk, KbDocument
from medagent.rag.chunking import chunk_pages, context_header
from medagent.rag.embeddings import Embedder, get_embedder
from medagent.rag.loaders import DocumentLoader, MedlinePlusLoader, PdfLoader
from medagent.rag.types import RawDocument

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
EMBED_BATCH = 64
HEADER_VERSION = 1  # bump when the header format changes: the hash then forces a re-ingest


@dataclass
class IngestReport:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    chunks: int = 0

    def __str__(self) -> str:
        return (
            f"{self.added} added, {self.updated} updated, {self.skipped} unchanged, "
            f"{self.chunks} chunks written"
        )


def document_hash(doc: RawDocument) -> str:
    """Hash of everything that affects the stored chunks (text, pages and metadata)."""
    h = hashlib.sha256()
    for part in (doc.title, doc.license, doc.attribution, doc.url or "", str(doc.is_public)):
        h.update(part.encode())
        h.update(b"\x00")
    for page in doc.pages:
        h.update(f"{page.page}\x00{page.text}\x00".encode())
    h.update(f"header:{HEADER_VERSION}\x00{context_header(doc)}".encode())
    return h.hexdigest()


def _embedding_text(header: str, text: str) -> str:
    return f"{header}\n\n{text}" if header else text


def ingest_documents(
    session: Session, embedder: Embedder, documents: Iterable[RawDocument]
) -> IngestReport:
    report = IngestReport()
    for doc in documents:
        digest = document_hash(doc)
        existing = session.scalars(
            select(KbDocument).where(
                KbDocument.source_key == doc.source_key, KbDocument.external_id == doc.external_id
            )
        ).one_or_none()
        if existing is not None and existing.content_hash == digest:
            report.skipped += 1
            continue

        chunks = chunk_pages(doc.pages)
        header = context_header(doc)
        if not chunks:
            report.skipped += 1
            continue
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            vectors.extend(
                embedder.embed_documents([_embedding_text(header, c.text) for c in batch])
            )

        if existing is None:
            existing = KbDocument(source_key=doc.source_key, external_id=doc.external_id)
            session.add(existing)
            report.added += 1
        else:
            existing.chunks.clear()  # delete-orphan removes the old chunks
            session.flush()
            report.updated += 1
        existing.title = doc.title
        existing.url = doc.url
        existing.license = doc.license
        existing.attribution = doc.attribution
        existing.is_public = doc.is_public
        existing.content_hash = digest
        existing.chunks = [
            KbChunk(
                chunk_index=c.index,
                page=c.page,
                content=c.text,
                context_header=header,
                embedding=v,
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        report.chunks += len(chunks)
        session.commit()  # per document: a crash loses at most one document of work
    return report


def build_loader(source: str, limit: int | None = None) -> DocumentLoader:
    if source == "medlineplus":
        files = sorted((RAW_DIR / "medlineplus").glob("mplus_topics_*.xml"))
        if not files:
            raise SystemExit(
                "No MedlinePlus XML found. Run: uv run python scripts/fetch_medlineplus.py"
            )
        return MedlinePlusLoader(files[-1], limit=limit)
    if source == "medical_book":
        return PdfLoader(
            RAW_DIR / "Medical_book.pdf",
            source_key="medical_book",
            title="Medical_book",
            license="All rights reserved (not licensed for redistribution)",
            attribution="Medical_book - local development only",
            is_public=False,  # the licence to publish it is not held: never retrieved when deployed
        )
    raise SystemExit(f"Unknown source '{source}'. Choose: medlineplus, medical_book")


def main() -> None:
    from medagent.db.session import get_sessionmaker

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("source", choices=["medlineplus", "medical_book"])
    parser.add_argument("--limit", type=int, default=None, help="only the first N documents")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    loader = build_loader(args.source, args.limit)
    with get_sessionmaker()() as session:
        report = ingest_documents(session, get_embedder(), loader.load())
    print(f"{args.source}: {report}")


if __name__ == "__main__":
    main()
