"""Product AGI persistence — the autonomous product-growth employee's workspace.

Tenant scoping is identical to the rest of the platform: every row is bound
to exactly one merchant and every query filters by ``merchant_id`` in SQL.

Four tables, each with one job:

  ``product_agent_runs``            one bounded autonomous execution
  ``product_agent_events``          the REAL activity feed the dashboard polls
  ``product_agent_findings``        what the agent observed, with evidence
  ``product_agent_recommendations`` what it concluded, with confidence + risk

There is deliberately NO ``product_agent_actions`` table. A recommendation
becomes work through the platform's existing ``agent_actions`` pipeline so
approval, verification, execution and audit stay in exactly one place.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
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
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.merchant import Merchant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductAgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded autonomous execution of the Product Agent loop."""

    __tablename__ = "product_agent_runs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Optional link to the shared AI Team analysis cycle, so a Product
    #: Agent run started by the orchestrator can be correlated with sibling
    #: agents. Informational only — every query still filters merchant_id.
    analysis_cycle_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    #: Run status from ``agents.product_agi.state.RunStatus``. The column must
    #: stay wide enough for the LONGEST member: ``approved_awaiting_execution``
    #: is 27 characters, which silently overflowed the original VARCHAR(24) on
    #: Postgres (SQLite ignores the width, so the test suite could not see it)
    #: and made every approve() roll back with StringDataRightTruncation.
    #: Keep this in sync with the enum — ``tests/test_product_agent_lifecycle.py``
    #: asserts every member fits.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    #: The agent's own stage machine (see agents/product_agi/state.py).
    current_stage: Mapped[str] = mapped_column(
        String(40), nullable=False, default="understand_catalog", index=True
    )
    #: Headline the dashboard renders. Composed from real measurements only.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Real aggregates for the dashboard header. Every value is measured or
    #: explicitly None — never a placeholder number.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Terminal status label for the approval banner: not_required |
    #: required | approved | rejected | executing | completed | failed.
    approval_status: Mapped[str | None] = mapped_column(
        String(24), nullable=True, index=True
    )
    state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    errors: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    products_analyzed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    opportunities_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    recommendations_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    merchant: Mapped[Merchant] = relationship("Merchant")
    events: Mapped[list[ProductAgentEvent]] = relationship(
        "ProductAgentEvent",
        foreign_keys="[ProductAgentEvent.run_id]",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    findings: Mapped[list[ProductAgentFinding]] = relationship(
        "ProductAgentFinding",
        foreign_keys="[ProductAgentFinding.run_id]",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list[ProductAgentRecommendation]] = relationship(
        "ProductAgentRecommendation",
        foreign_keys="[ProductAgentRecommendation.run_id]",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_pa_runs_merchant_status", "merchant_id", "status"),
    )


class ProductAgentEvent(UUIDPrimaryKeyMixin, Base):
    """A REAL execution event emitted by the Product Agent loop.

    The dashboard's activity feed is rendered exclusively from these rows.
    There is no decorative activity anywhere in the Product Agent UI.
    """

    __tablename__ = "product_agent_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(60), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    run: Mapped[ProductAgentRun] = relationship(
        "ProductAgentRun", foreign_keys=[run_id], back_populates="events"
    )

    __table_args__ = (
        Index("ix_pa_events_run_seq", "run_id", "seq"),
    )


class ProductAgentFinding(UUIDPrimaryKeyMixin, Base):
    """Something the agent observed, with the evidence that supports it.

    ``evidence`` holds a list of safe statements each tied to the MCP tool
    that produced it, so a finding on the dashboard can always be traced
    back to a tool call.
    """

    __tablename__ = "product_agent_findings"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: catalog | performance | inventory | content | pricing | bundle |
    #: research | data_gap
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: info | low | medium | high
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="info", index=True
    )
    #: 0..1, or None when the finding is a factual observation with no
    #: modelled probability attached.
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    product_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    run: Mapped[ProductAgentRun] = relationship(
        "ProductAgentRun", foreign_keys=[run_id], back_populates="findings"
    )

    __table_args__ = (
        Index("ix_pa_findings_run_type", "run_id", "type"),
    )


class ProductAgentRecommendation(UUIDPrimaryKeyMixin, Base):
    """An evidence-backed conclusion the agent proposes to act on.

    Every field the dashboard renders is stored so the card is reproducible
    after a refresh: problem, recommendation, why-now, evidence,
    confidence, expected impact (or an explicit unavailability reason),
    risk, affected products and whether approval is required.

    ``action_id`` points at the EXISTING ``agent_actions`` row created for
    this recommendation. The Product Agent never approves it and never
    executes it.
    """

    __tablename__ = "product_agent_recommendations"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: inventory | content | pricing | bundle | merchandising | research
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    why_now: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 0..1
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    #: List of safe evidence statements with their tool references.
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    #: {"status": "available" | "unavailable", "text": ..., "basis": ...}
    expected_impact: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_products: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    #: Deterministic product_intelligence category this came from, so a
    #: recommendation can be traced to the tool that enabled it.
    basis: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action_required: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    approval_required: Mapped[bool] = mapped_column(
        nullable=False, default=True
    )
    #: proposed | awaiting_approval | approved | rejected | executed | failed
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="proposed", index=True
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    run: Mapped[ProductAgentRun] = relationship(
        "ProductAgentRun", foreign_keys=[run_id], back_populates="recommendations"
    )
    action: Mapped[AgentAction | None] = relationship("AgentAction")

    __table_args__ = (
        Index("ix_pa_recs_run_type", "run_id", "type"),
    )


__all__ = [
    "ProductAgentEvent",
    "ProductAgentFinding",
    "ProductAgentRecommendation",
    "ProductAgentRun",
]