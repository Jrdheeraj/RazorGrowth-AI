"""Marketing AGI persistence — completely isolated from the legacy MarketingAgent.

These tables belong to the autonomous MarketingAGI module only. Tenant
scoping is identical to the rest of the platform: every row is bound to
exactly one merchant and every query filters by merchant_id in SQL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.merchant import Merchant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketingAGIRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded autonomous execution of the MarketingAGI loop."""

    __tablename__ = "marketing_agi_runs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True
    )
    phase: Mapped[str] = mapped_column(
        String(40), nullable=False, default="load_context"
    )
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    errors: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    merchant: Mapped[Merchant] = relationship("Merchant")
    events: Mapped[list[MarketingAGIEvent]] = relationship(
        "MarketingAGIEvent",
        foreign_keys="[MarketingAGIEvent.run_id]",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_magi_runs_merchant_status", "merchant_id", "status"),
    )


class MarketingAGIEvent(UUIDPrimaryKeyMixin, Base):
    """A REAL execution event emitted by the MarketingAGI loop.

    The frontend live workstream is driven exclusively by these rows —
    no decorative UI animations exist anywhere.
    """

    __tablename__ = "marketing_agi_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketing_agi_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(60), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    run: Mapped[MarketingAGIRun] = relationship(
        "MarketingAGIRun", foreign_keys=[run_id], back_populates="events"
    )

    __table_args__ = (
        Index("ix_magi_events_run_seq", "run_id", "seq"),
    )


class MarketingAGICampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The MarketingAGI campaign workspace: one concrete piece of marketing work.

    Lifecycle: idea -> research -> draft -> verify -> ready_for_approval ->
    approved -> executing -> completed -> measuring -> learned (or rejected).
    """

    __tablename__ = "marketing_agi_campaigns"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketing_agi_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_key: Mapped[str] = mapped_column(String(140), nullable=False)
    workflow: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    integration_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft_only"
    )
    lifecycle: Mapped[str] = mapped_column(
        String(30), nullable=False, default="idea", index=True
    )
    audience: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    audience_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expected_impact: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    estimated_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    success_metric: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    merchant: Mapped[Merchant] = relationship("Merchant")
    action: Mapped[AgentAction | None] = relationship("AgentAction")

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "campaign_key", name="uq_magi_campaigns_merchant_key"
        ),
    )


class MarketingAGIHandoff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Agent-to-agent collaboration handoff (interface for future specialists)."""

    __tablename__ = "marketing_agi_handoffs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketing_agi_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    specialist: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    merchant: Mapped[Merchant] = relationship("Merchant")


class MarketingAGILearning(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measured outcome of an executed MarketingAGI campaign.

    NEVER fabricated: when real outcome data is unavailable the row says
    so (status=measurement_pending) instead of inventing a result.
    """

    __tablename__ = "marketing_agi_learnings"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketing_agi_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="measuring"
    )
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actual: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    insights: Mapped[str | None] = mapped_column(Text, nullable=True)
    learned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    merchant: Mapped[Merchant] = relationship("Merchant")
