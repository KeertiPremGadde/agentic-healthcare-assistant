"""Embeddings behind an interface so the provider can be swapped (local FastEmbed today,
a hosted API later) without touching ingestion or retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from medagent.core.config import Settings, get_settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings (no torch, no API key). The model downloads on first use."""

    def __init__(self, model_name: str, dim: int) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model: TextEmbedding | None = None

    @property
    def dim(self) -> int:
        return self._dim

    def _get_model(self) -> TextEmbedding:
        from fastembed import TextEmbedding  # imported lazily: keeps app start-up fast

        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._get_model().embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        # For bge-small-en-v1.5 query_embed equals embed (no instruction prefix; verified).
        # Kept separate so models that need a query prefix (e5, bge v1) can be swapped in.
        return [float(x) for x in next(iter(self._get_model().query_embed(text)))]


def get_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    if settings.embedding_provider == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
