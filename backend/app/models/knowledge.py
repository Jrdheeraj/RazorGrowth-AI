"""
KnowledgeDocument and KnowledgeChunk models.

These models form the retrieval layer of the Agentic RAG pipeline.

KnowledgeDocument — a semantic representation of a merchant data entity
                    (product, customer, order, etc.)
KnowledgeChunk    — a searchable chunk with a pgvector embedding column.

The embedding column uses pgvector's VECTOR type on PostgreSQL.
On SQLite (test environment) the column is rendered as TEXT and bypassed
by the test conftest.py JSONB-swap event.

Checksums prevent re-embedding content that has not changed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A semantic document derived from a merchant data entity.

    source_type examples: product, customer, order, payment, opportunity, merchant
    checksum:  SHA-256 of content — prevents redundant re-embedding.
    """
    __tablename__ = "knowledge_documents"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant")
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # One document per source entity per merchant — enforces idempotency
        UniqueConstraint(
            "merchant_id", "source_type", "source_id",
            name="uq_knowledge_documents_merchant_source",
        ),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} source_type={self.source_type} source_id={self.source_id!r}>"


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A searchable chunk from a KnowledgeDocument.

    The embedding column holds a pgvector VECTOR. On PostgreSQL this enables
    cosine-similarity nearest-neighbour search. In tests (SQLite) this column
    is treated as JSON text and search falls back to keyword matching.
    """
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    # embedding is declared as JSONB here and handled by the vector column
    # via an Alembic migration that adds the vector type with pgvector.
    # We use JSONB as a placeholder that stores the embedding as a JSON array;
    # Alembic will ALTER it to vector(1536) on PostgreSQL.
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    document: Mapped[KnowledgeDocument] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )
    merchant: Mapped[Merchant] = relationship("Merchant")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index",
            name="uq_knowledge_chunks_doc_index",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeChunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"
