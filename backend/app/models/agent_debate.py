"""Agent Debate models — Phase 7 AI Growth Team."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import (
    AgentSpecialty,
    DebateStatus,
    FindingType,
    TaskStatus,
)

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentDebate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A debate session for a growth objective.

    Manager creates investigation → Specialists investigate → Findings compared
    → Conflicts represented → Manager synthesizes → Final recommendation.
    """
    __tablename__ = "agent_debates"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DebateStatus] = mapped_column(
        Enum(DebateStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=DebateStatus.initiated,
        server_default=DebateStatus.initiated.value,
        index=True,
    )
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    manager_agent_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    final_synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    merchant: Mapped[Merchant] = relationship("Merchant")
    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", back_populates="debate", cascade="all, delete-orphan"
    )
    findings: Mapped[list["AgentFinding"]] = relationship(
        "AgentFinding", back_populates="debate", cascade="all, delete-orphan"
    )
    messages: Mapped[list["AgentMessage"]] = relationship(
        "AgentMessage", back_populates="debate", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_agent_debates_merchant_status", "merchant_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<AgentDebate id={self.id} objective={self.objective[:50]} status={self.status}>"


class AgentTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A task assigned by the Manager to a specialist agent."""
    __tablename__ = "agent_tasks"

    debate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_debates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_to: Mapped[AgentSpecialty] = mapped_column(
        Enum(AgentSpecialty, native_enum=False, validate_strings=True),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=TaskStatus.assigned,
        server_default=TaskStatus.assigned.value,
        index=True,
    )
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    debate: Mapped[AgentDebate] = relationship("AgentDebate", back_populates="tasks")
    merchant: Mapped[Merchant] = relationship("Merchant")

    __table_args__ = (
        Index("ix_agent_tasks_debate_status", "debate_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<AgentTask id={self.id} debate={self.debate_id} assigned_to={self.assigned_to} status={self.status}>"


class AgentFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A finding produced by a specialist agent during investigation."""
    __tablename__ = "agent_findings"

    debate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_debates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_specialty: Mapped[AgentSpecialty] = mapped_column(
        Enum(AgentSpecialty, native_enum=False, validate_strings=True),
        nullable=False,
        index=True,
    )
    finding_type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, native_enum=False, validate_strings=True),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    uncertainty_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    supports_recommendation: Mapped[bool | None] = mapped_column(nullable=True)

    # Relationships
    debate: Mapped[AgentDebate] = relationship("AgentDebate", back_populates="findings")
    task: Mapped[AgentTask | None] = relationship("AgentTask")
    merchant: Mapped[Merchant] = relationship("Merchant")

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_agent_findings_confidence_range",
        ),
        Index("ix_agent_findings_debate_type", "debate_id", "finding_type"),
    )

    def __repr__(self) -> str:
        return f"<AgentFinding id={self.id} specialty={self.agent_specialty} type={self.finding_type} confidence={self.confidence}>"


class AgentMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A message exchanged during the debate phase."""
    __tablename__ = "agent_messages"

    debate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_debates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_agent: Mapped[AgentSpecialty] = mapped_column(
        Enum(AgentSpecialty, native_enum=False, validate_strings=True),
        nullable=False,
    )
    to_agent: Mapped[AgentSpecialty | None] = mapped_column(
        Enum(AgentSpecialty, native_enum=False, validate_strings=True),
        nullable=True,
    )  # None = broadcast
    message_type: Mapped[str] = mapped_column(String(50), nullable=False)  # question, response, challenge, synthesis
    content: Mapped[str] = mapped_column(Text, nullable=False)
    references: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)  # references to findings

    # Relationships
    debate: Mapped[AgentDebate] = relationship("AgentDebate", back_populates="messages")
    merchant: Mapped[Merchant] = relationship("Merchant")

    __table_args__ = (
        Index("ix_agent_messages_debate_agent", "debate_id", "from_agent"),
    )

    def __repr__(self) -> str:
        return f"<AgentMessage id={self.id} debate={self.debate_id} from={self.from_agent} type={self.message_type}>"