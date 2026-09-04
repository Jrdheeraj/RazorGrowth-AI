"""Agent Debate repositories."""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.agent_debate import AgentDebate, AgentTask, AgentFinding, AgentMessage
from backend.app.models.enums import DebateStatus, TaskStatus, FindingType
from backend.app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class AgentDebateRepository(BaseRepository[AgentDebate]):
    model = AgentDebate

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        status: DebateStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentDebate]:
        stmt = select(AgentDebate).where(AgentDebate.merchant_id == merchant_id)
        if status:
            stmt = stmt.where(AgentDebate.status == status)
        stmt = stmt.order_by(AgentDebate.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def get_with_details(self, debate_id: uuid.UUID) -> AgentDebate | None:
        stmt = (
            select(AgentDebate)
            .options(
                selectinload(AgentDebate.tasks),
                selectinload(AgentDebate.findings),
                selectinload(AgentDebate.messages),
            )
            .where(AgentDebate.id == debate_id)
        )
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        objective: str,
        manager_agent_id: str | None = None,
        context: dict | None = None,
    ) -> AgentDebate:
        debate = AgentDebate(
            merchant_id=merchant_id,
            objective=objective,
            manager_agent_id=manager_agent_id,
            context=context,
            status=DebateStatus.initiated,
        )
        return self.add(debate)


class AgentTaskRepository(BaseRepository[AgentTask]):
    model = AgentTask

    def list_by_debate(self, debate_id: uuid.UUID) -> list[AgentTask]:
        stmt = select(AgentTask).where(AgentTask.debate_id == debate_id).order_by(AgentTask.created_at)
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, task_id: uuid.UUID) -> AgentTask | None:
        return self.db.get(AgentTask, task_id)

    def create(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        assigned_to: str,
        title: str,
        description: str | None = None,
        input_data: dict | None = None,
    ) -> AgentTask:
        task = AgentTask(
            debate_id=debate_id,
            merchant_id=merchant_id,
            assigned_to=assigned_to,
            title=title,
            description=description,
            input_data=input_data,
            status=TaskStatus.assigned,
        )
        return self.add(task)

    def update_status(self, task_id: uuid.UUID, status: TaskStatus, output_data: dict | None = None, error: str | None = None) -> AgentTask | None:
        task = self.get_by_id(task_id)
        if task:
            task.status = status
            if output_data:
                task.output_data = output_data
            if error:
                task.error = error
            if status == TaskStatus.completed:
                from datetime import datetime, timezone
                task.completed_at = datetime.now(timezone.utc)
            self.db.flush()
        return task


class AgentFindingRepository(BaseRepository[AgentFinding]):
    model = AgentFinding

    def list_by_debate(self, debate_id: uuid.UUID) -> list[AgentFinding]:
        stmt = select(AgentFinding).where(AgentFinding.debate_id == debate_id).order_by(AgentFinding.created_at)
        return list(self.db.scalars(stmt).all())

    def list_by_debate_and_type(self, debate_id: uuid.UUID, finding_type: str) -> list[AgentFinding]:
        stmt = select(AgentFinding).where(
            AgentFinding.debate_id == debate_id,
            AgentFinding.finding_type == finding_type,
        ).order_by(AgentFinding.created_at)
        return list(self.db.scalars(stmt).all())

    def create(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        task_id: uuid.UUID | None,
        agent_specialty: str,
        finding_type: str,
        title: str,
        description: str | None = None,
        evidence: list | None = None,
        confidence: float = 0.5,
        uncertainty_notes: str | None = None,
        supports_recommendation: bool | None = None,
    ) -> AgentFinding:
        from decimal import Decimal
        finding = AgentFinding(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_id,
            agent_specialty=agent_specialty,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=Decimal(str(confidence)),
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return self.add(finding)


class AgentMessageRepository(BaseRepository[AgentMessage]):
    model = AgentMessage

    def list_by_debate(self, debate_id: uuid.UUID) -> list[AgentMessage]:
        stmt = select(AgentMessage).where(AgentMessage.debate_id == debate_id).order_by(AgentMessage.created_at)
        return list(self.db.scalars(stmt).all())

    def create(
        self,
        *,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
        from_agent: str,
        to_agent: str | None,
        message_type: str,
        content: str,
        references: list | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            references=references,
        )
        return self.add(message)
