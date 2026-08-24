"""
OpenAI embedding provider implementation.

Uses text-embedding-3-small (1536 dimensions) by default.
Model is configurable via:
    EMBEDDING_MODEL=text-embedding-3-small

API key is never logged.
"""
from __future__ import annotations

import logging

from backend.app.ai.embeddings.base import BaseEmbeddingProvider, EmbeddingError

log = logging.getLogger(__name__)

# Dimensionality map for known OpenAI embedding models
_OPENAI_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embeddings via the /embeddings endpoint."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required. Run: pip install openai")

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dims = _OPENAI_DIMENSIONS.get(model, 1536)
        log.info("OpenAIEmbeddingProvider initialised. model=%s dims=%d", model, self._dims)

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
            # Sort by index to guarantee order matches input
            sorted_data = sorted(response.data, key=lambda d: d.index)
            log.debug("Embedded %d documents. model=%s", len(texts), self._model)
            return [item.embedding for item in sorted_data]
        except Exception as exc:
            log.error("Embedding call failed: %s", type(exc).__name__)
            raise EmbeddingError(f"Embedding failed: {type(exc).__name__}") from exc


def build_embedding_provider(
    provider: str,
    api_key: str,
    model: str,
) -> BaseEmbeddingProvider:
    """Factory for embedding providers."""
    if provider.lower() == "openai":
        return OpenAIEmbeddingProvider(api_key=api_key, model=model)
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider!r}. Supported: openai")
