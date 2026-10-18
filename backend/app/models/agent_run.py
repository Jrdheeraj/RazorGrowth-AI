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

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import AgentRunStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of one specialised agent within an orchestrator run.

    Step identity, not agent identity
    ---------------------------------
    A single agent legitimately executes several times inside one cycle --
    ``GROWTH_TEAM_PLAN`` runs MarketingAgent three times (investigate,
    cross_examine, rebut) and GrowthMemoryAgent twice. A uniqueness rule on
    ``(orchestrator_run_id, agent_name)`` would therefore reject valid
    workflows, so the deduplicated unit is a STEP:

        (workflow_id, step_key, attempt)

    ``step_key`` is derived from the plan position (mode + index + agent +
    phase), so it is stable across processes and code paths, while remaining
    distinct for every legitimate repetition. ``attempt`` is what makes a
    replan or retry add history instead of colliding with the first try.

    Legacy rows (written before workflow tracking) have NULL in all three and
    are simply outside the constraint.
    """

    __tablename__ = "agent_runs"

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    #: The cycle this step belongs to. NULL for legacy rows and for
    #: single-agent launches, which are not part of a multi-step cycle.
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    orchestrator_run_id: Mapped[uuid.UUID | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    #: Stable identity of this step within its cycle, derived from the plan
    #: position. See the class docstring for why this, and not agent_name,
    #: is the deduplication key.
    step_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Zero-based position in the materialised plan. Makes "how far did it
    #: get" answerable with a plain integer comparison.
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 1 for the first try. A replan or retry increments it, preserving the
    #: earlier attempt's row instead of overwriting it.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[AgentRunStatus] = mapped_column(
        String(24), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="deep")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Proof of life while the owning process works. A running step whose
    #: heartbeat has gone cold is what makes a crashed cycle detectable.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
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
    workflow: Mapped["AgentWorkflowRun | None"] = relationship(
        "AgentWorkflowRun", back_populates="agent_runs"
    )

    __table_args__ = (
        # The deduplication unit is a STEP ATTEMPT, not an agent. Legitimate
        # repetition (MarketingAgent x3 in growth_team) is allowed because each
        # occurrence has its own step_key; a duplicate replay of the same
        # logical attempt is rejected by the database itself, not by a
        # read-then-write race in application code.
        #
        # NULLs (legacy rows, single-agent launches) do not collide in either
        # PostgreSQL or SQLite, so no data backfill is required to adopt it.
        UniqueConstraint(
            "workflow_id",
            "step_key",
            "attempt",
            name="uq_agent_runs_workflow_step_attempt",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_name} status={self.status}>"
