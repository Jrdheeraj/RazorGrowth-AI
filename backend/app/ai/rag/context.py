"""
Retrieval context data structures.

Every item returned from retrieval must carry its source metadata so the
AI layer can produce traceable, non-fabricated citations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedItem:
    """
    A single retrieved knowledge chunk with full provenance.

    similarity: cosine similarity score 0–1 (higher = more relevant).
                None when retrieval was keyword-based (SQLite fallback).
    """
    content: str
    source_type: str          # e.g. "product", "customer", "order"
    source_id: str            # stable entity ID
    document_id: str          # KnowledgeDocument.id
    chunk_id: str             # KnowledgeChunk.id
    similarity: float | None  # None for non-vector fallback
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "similarity": self.similarity,
            "content_preview": self.content[:200],
            "metadata": self.metadata,
        }


@dataclass
class RetrievedContext:
    """The full result of a retrieval call."""
    query: str
    items: list[RetrievedItem] = field(default_factory=list)
    retrieval_method: str = "vector"  # "vector" | "keyword"

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0

    def format_for_prompt(self) -> str:
        """Render context items as a prompt-ready string block."""
        if self.is_empty:
            return "No relevant knowledge retrieved."
        lines = []
        for i, item in enumerate(self.items, 1):
            sim_str = f" (similarity: {item.similarity:.3f})" if item.similarity is not None else ""
            lines.append(
                f"[{i}] Source: {item.source_type} / {item.source_id}{sim_str}\n"
                f"{item.content}\n"
            )
        return "\n".join(lines)
