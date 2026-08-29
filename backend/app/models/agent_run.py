"""AgentRun model — Phase 5 agent observability + audit trail.

Records every specialised-agent execution: WHO ran, WHAT tools it used,
WHAT it produced, HOW LONG each layer took, and any errors.
NEVER stored here (or anywhere): API keys, secrets, credentials,
payment credentials.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import AgentRunStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of one specialised agent within an orchestrator run."""

    __tablename__ = "agent_runs"

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    orchestrator_run_id: Mapped[uuid.UUID | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        String(20), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="deep")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tools_used: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    opportunities_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actions_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insights_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    experiments_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # Observability latency metrics (milliseconds)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Model identity for the run (no keys — names only)
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="agent_runs"
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_name} status={self.status}>"
