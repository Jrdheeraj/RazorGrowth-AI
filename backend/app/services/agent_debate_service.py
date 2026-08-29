"""Agent Debate Service — Phase 7 AI Growth Team."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.agent_debate import AgentDebate, AgentTask, AgentFinding, AgentMessage
from backend.app.models.enums import (
    AgentSpecialty,
    DebateStatus,
    FindingType,
    TaskStatus,
)
from backend.app.repositories.agent_debate import (
    AgentDebateRepository,
    AgentTaskRepository,
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class AgentDebateService:
    """Service for managing agent debate sessions."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._debate_repo = AgentDebateRepository(db)
        self._task_repo = AgentTaskRepository(db)
        self._finding_repo = AgentFindingRepository(db)
        self._message_repo = AgentMessageRepository(db)

    # ─── Debate management ──────────────────────────────────────────────────

    def create_debate(
        self,
        *,
        merchant_id: uuid.UUID,
        objective: str,
        manager_agent_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentDebate:
        """Create a new debate session for a growth objective."""
        debate = self._debate_repo.create(
            merchant_id=merchant_id,
            objective=objective,
            manager_agent_id=manager_agent_id,
            context=context,
        )
        self._db.flush()
        log.info("Debate created. id=%s merchant=%s objective=%s", str(debate.id), merchant_id, objective[:100])
        return debate

    def get_debate(self, debate_id: uuid.UUID) -> AgentDebate | None:
        return self._debate_repo.get_with_details(debate_id)

    def list_debates(
        self,
        merchant_id: uuid.UUID,
        *,
        status: DebateStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentDebate]:
        return self._debate_repo.list_by_merchant(merchant_id, status=status, limit=limit, offset=offset)

    def update_debate_status(self, debate_id: uuid.UUID, status: DebateStatus) -> AgentDebate | None:
        debate = self._debate_repo.get_by_id(debate_id)
        if debate:
            debate.status = status
            self._db.flush()
        return debate

    def set_debate_synthesis(self, debate_id: uuid.UUID, synthesis: str) -> AgentDebate | None:
        debate = self._debate_repo.get_by_id(debate_id)
        if debate:
            debate.final_synthesis = synthesis
            debate.status = DebateStatus.concluded
            self._db.flush()
        return debate

    def link_recommendation(self, debate_id: uuid.UUID, recommendation_id: uuid.UUID) -> AgentDebate | None:
        debate = self._debate_repo.get_by_id(debate_id)
        if debate:
            debate.recommendation_id = recommendation_id
            self._db.flush()
        return debate

    # ─── Task management ────────────────────────────────────────────────────

    def create_task(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        assigned_to: AgentSpecialty,
        title: str,
        description: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> AgentTask:
        task = self._task_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            assigned_to=assigned_to.value,
            title=title,
            description=description,
            input_data=input_data,
        )
        self._db.flush()
        return task

    def get_task(self, task_id: uuid.UUID) -> AgentTask | None:
        return self._task_repo.get_by_id(task_id)

    def list_tasks_by_debate(self, debate_id: uuid.UUID) -> list[AgentTask]:
        return self._task_repo.list_by_debate(debate_id)

    def complete_task(
        self,
        task_id: uuid.UUID,
        *,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AgentTask | None:
        status = TaskStatus.failed if error else TaskStatus.completed
        return self._task_repo.update_status(task_id, status, output_data, error)

    # ─── Finding management ─────────────────────────────────────────────────

    def add_finding(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        task_id: uuid.UUID | None,
        agent_specialty: AgentSpecialty,
        finding_type: FindingType,
        title: str,
        description: str | None = None,
        evidence: list[Any] | None = None,
        confidence: float = 0.5,
        uncertainty_notes: str | None = None,
        supports_recommendation: bool | None = None,
    ) -> AgentFinding:
        finding = self._finding_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_id,
            agent_specialty=agent_specialty.value,
            finding_type=finding_type.value,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        self._db.flush()
        return finding

    def list_findings_by_debate(self, debate_id: uuid.UUID) -> list[AgentFinding]:
        return self._finding_repo.list_by_debate(debate_id)

    def list_findings_by_type(self, debate_id: uuid.UUID, finding_type: FindingType) -> list[AgentFinding]:
        return self._finding_repo.list_by_debate_and_type(debate_id, finding_type.value)

    # ─── Message management ─────────────────────────────────────────────────

    def add_message(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        from_agent: AgentSpecialty,
        to_agent: AgentSpecialty | None,
        message_type: str,
        content: str,
        references: list[Any] | None = None,
    ) -> AgentMessage:
        message = self._message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=from_agent.value,
            to_agent=to_agent.value if to_agent else None,
            message_type=message_type,
            content=content,
            references=references,
        )
        self._db.flush()
        return message

    def list_messages_by_debate(self, debate_id: uuid.UUID) -> list[AgentMessage]:
        return self._message_repo.list_by_debate(debate_id)

    # ─── Analysis helpers ───────────────────────────────────────────────────

    def get_conflicting_findings(self, debate_id: uuid.UUID) -> dict[str, list[AgentFinding]]:
        """Get supporting vs opposing findings for the debate."""
        return {
            "supporting": self.list_findings_by_type(debate_id, FindingType.supporting),
            "opposing": self.list_findings_by_type(debate_id, FindingType.opposing),
            "neutral": self.list_findings_by_type(debate_id, FindingType.neutral),
            "uncertainty": self.list_findings_by_type(debate_id, FindingType.uncertainty),
        }

    def get_debate_summary(self, debate_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a structured summary of the debate for synthesis."""
        debate = self.get_debate(debate_id)
        if not debate:
            return None

        findings = self.list_findings_by_debate(debate_id)
        messages = self.list_messages_by_debate(debate_id)
        tasks = self.list_tasks_by_debate(debate_id)

        conflicting = self.get_conflicting_findings(debate_id)

        return {
            "debate_id": str(debate.id),
            "objective": debate.objective,
            "status": debate.status.value,
            "tasks": [
                {
                    "id": str(t.id),
                    "assigned_to": t.assigned_to,
                    "title": t.title,
                    "status": t.status.value,
                    "output": t.output_data,
                }
                for t in tasks
            ],
            "findings_summary": {
                "total": len(findings),
                "supporting": len(conflicting["supporting"]),
                "opposing": len(conflicting["opposing"]),
                "neutral": len(conflicting["neutral"]),
                "uncertainty": len(conflicting["uncertainty"]),
            },
            "findings": [
                {
                    "id": str(f.id),
                    "agent": f.agent_specialty,
                    "type": f.finding_type,
                    "title": f.title,
                    "description": f.description,
                    "confidence": float(f.confidence),
                    "supports_recommendation": f.supports_recommendation,
                }
                for f in findings
            ],
            "messages": [
                {
                    "from": m.from_agent,
                    "to": m.to_agent,
                    "type": m.message_type,
                    "content": m.content,
                }
                for m in messages
            ],
            "final_synthesis": debate.final_synthesis,
        }