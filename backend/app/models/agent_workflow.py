"""
AgentWorkflowRun — the durable, resumable unit of multi-agent execution.

Why this table exists
---------------------
``agent_runs`` records that an agent *ran*. It never recorded that a
multi-agent cycle was *in flight*, which step it had reached, or who owned it.
Consequently a crashed ``GrowthAgentOrchestrator`` left behind a set of
per-agent rows with no cycle-level truth: nothing said "this cycle was
half-finished", nothing could say which steps were done, and nothing stopped a
later invocation from replaying the entire plan under the same run id.

This row is that missing truth. One row per (merchant, run id):

* ``plan`` is the MATERIALISED step list actually executed, so a resume
  replays exactly the steps the first attempt ran rather than whatever the
  code's plan constants say today.
* ``plan_fingerprint`` detects a plan that changed underneath an unfinished
  cycle. Silently mixing old results into a new plan would corrupt the final
  synthesis, so a mismatch is refused instead.
* ``lease_owner`` / ``lease_expires_at`` give single-writer ownership through
  a compare-and-set UPDATE. A healthy worker is never taken over; only an
  expired lease is.

It stores execution metadata only. No merchant business data, no prompts, no
credentials -- the step list is agent names and phases.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import WorkflowStatus

if TYPE_CHECKING:
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.merchant import Merchant


class AgentWorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One resumable orchestration cycle for one merchant."""

    __tablename__ = "agent_workflow_runs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The public correlation id surfaced as ``orchestrator_run_id`` in the
    #: API. Unique per merchant: one id names exactly one cycle, so re-using
    #: it can never silently fork a second cycle.
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="deep")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowStatus.running.value, index=True
    )

    #: SHA-256 of the materialised step list. Detects plan drift on resume.
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    #: The materialised plan: [{"step_key", "step_index", "agent_name",
    #: "phase", "params"}, ...] in execution order. Resume replays THIS, not
    #: the module-level plan constant.
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    #: Number of steps in the plan, so "how far did it get" is answerable
    #: without parsing the JSON.
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Single-writer ownership. ``claim`` performs a compare-and-set UPDATE
    #: against these, so two concurrent resumes cannot both own the cycle.
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Last proof of life from the owning process.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Fencing token. Incremented by every successful ownership claim, and by
    #: the stale-workflow sweep when it takes a cycle over.
    #:
    #: A lease alone cannot stop a paused worker: it can wake up after its lease
    #: expired and a new owner claimed the cycle, then happily write. The
    #: generation is what closes that window. Every protected write carries the
    #: generation its worker claimed, and is rejected if the stored generation
    #: has moved on. Generation 0 is the sentinel for "never claimed", so a
    #: worker that never claimed can never pass the check.
    lease_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    #: When an operator asked for this cycle to stop.
    #:
    #: Set by the cancel endpoint and polled by the orchestrator between steps,
    #: so cancellation survives across processes. A cooperative flag held only
    #: in the web process would be invisible to a worker running in another one,
    #: and lost on any restart.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    errors: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="agent_workflow_runs"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # One run id names exactly one cycle, per tenant.
        UniqueConstraint("merchant_id", "run_id", name="uq_agent_workflow_runs_merchant_run"),
        Index(
            "ix_agent_workflow_runs_merchant_status",
            "merchant_id",
            "status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AgentWorkflowRun run_id={self.run_id} mode={self.mode} "
            f"status={self.status}>"
        )
