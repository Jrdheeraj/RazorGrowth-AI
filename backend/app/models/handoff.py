"""
Cross-agent handoff persistence.

Deliberately a separate table from ``agent_actions``. A handoff is an
internal orchestration record; it is NOT a merchant-approvable proposal and
must never appear in the Actions approval console or be executable. Storing
handoffs in ``agent_actions`` would have made them approvable by accident.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentHandoff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One structured request from a source agent to a destination agent.

    ``status`` moves: pending → dispatched → completed | failed | refused.
    ``fingerprint`` makes re-requesting the same (source, destination, task)
    idempotent while the handoff is still open.
    """

    __tablename__ = "agent_handoffs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    destination_agent: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    #: Stable hash of (source, destination, task) — duplicate-dispatch guard.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Correlates this handoff with the orchestrator run that created it.
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: Delegation chain length; bounded by services.handoff.MAX_DEPTH.
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Minimal, JSON-serialisable evidence crossing the agent boundary.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[uuid.UUID | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: True once the destination has actually run. Makes "did this handoff
    #: really dispatch?" answerable with a single query.
    dispatched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    #: No ORM relationship back to Merchant on purpose: `Merchant` does not
    #: declare a `handoffs` back-reference, and adding one would touch a
    #: model shared by every other agent. Queries here are always explicitly
    #: merchant-scoped, which is the property that actually matters.

    __table_args__ = (
        Index("ix_agent_handoffs_merchant_status", "merchant_id", "status"),
        Index("ix_agent_handoffs_merchant_fingerprint", "merchant_id", "fingerprint"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentHandoff {self.source_agent}->{self.destination_agent} "
            f"status={self.status}>"
        )