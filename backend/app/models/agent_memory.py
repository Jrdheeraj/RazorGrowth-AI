"""AgentMemory model — Phase 5 growth memory (Feature 10/11).

Structured memory of what was recommended, what happened, and what was
learned. Embeddings are stored as JSON float arrays and compared with
in-process cosine similarity at retrieval time; retrieval is ALWAYS
scoped to a single merchant so memory never leaks across tenants.
(pgvector remains used for knowledge_chunks; memory volumes are small
enough that in-process similarity is deterministic, dependency-free,
and fully testable.)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import MemoryType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class AgentMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One remembered fact/outcome/preference for exactly one merchant."""

    __tablename__ = "agent_memories"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_type: Mapped[MemoryType] = mapped_column(String(40), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Float array embedding (JSON) — optional; retrieval falls back to recency+keyword
    embedding: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    source_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    importance: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("0.50")
    )
    outcome_variance_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    memory_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="agent_memories"
    )

    __table_args__ = (
        Index("ix_agent_memories_merchant_type", "merchant_id", "memory_type"),
    )

    def __repr__(self) -> str:
        return f"<AgentMemory {self.memory_type} merchant={self.merchant_id}>"
