"""Embedding provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """
    Abstract embedding provider.

    Concrete implementations must be stateless — safe to reuse across requests.
    """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding vector dimensionality."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Embed a single string. Raises EmbeddingError on failure."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple strings in a single batched call where possible.

        Returns a list of float vectors in the same order as input.
        Raises EmbeddingError on failure.
        """


class EmbeddingError(Exception):
    """Raised when an embedding call fails."""
