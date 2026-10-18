"""AgentAction model — records every action an AI agent requests or performs."""
from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import AgentActionStatus, AgentActionType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.opportunity import GrowthOpportunity


class AgentAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Every action requested or executed by an AI agent.

    This model is central to the human-in-the-loop approval workflow:
        AI recommendation → merchant approval → agent execution → audit trail

    The system must never silently execute money-related actions.
    approved_by / requested_by record who authorised each step.
    """
    __tablename__ = "agent_actions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[AgentActionType] = mapped_column(
        String(50), nullable=False, index=True
    )
    status: Mapped[AgentActionStatus] = mapped_column(
        String(20),
        nullable=False,
        default=AgentActionStatus.requested,
        server_default=AgentActionStatus.requested.value,
        index=True,
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Stable fingerprint of a LOGICALLY IDENTICAL proposal, scoped to the
    #: merchant. Two calls proposing the same thing for the same workflow --
    #: a retry, a replay, two workers racing -- produce the same key, and the
    #: unique constraint turns the second into a reference to the first.
    #:
    #: NULL means "no idempotency was offered", which is how every caller
    #: behaved before this column existed; NULLs do not collide in PostgreSQL
    #: or SQLite, so historical rows need no backfill.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The cycle this proposal came from, when known. Lets a merchant trace a
    #: pending action back to the workflow that produced it, and keeps the
    #: idempotency scope tied to one execution rather than to all time.
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Structured payloads stored as JSONB — typed at application layer
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[uuid.UUID | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship(
        "Merchant", back_populates="agent_actions"
    )
    opportunity: Mapped[GrowthOpportunity | None] = relationship(
        "GrowthOpportunity", back_populates="agent_actions"
    )

    __table_args__ = (
        # FK columns use index=True; no duplicate Index() entries needed.
        #
        # Enforced in the DATABASE, not by a read-then-write check in Python:
        # two concurrent retries can both miss a prior lookup, and only a
        # unique index makes the second one lose deterministically.
        UniqueConstraint(
            "merchant_id",
            "idempotency_key",
            name="uq_agent_actions_merchant_idempotency",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentAction id={self.id} type={self.action_type} status={self.status}>"
