"""Agent Debate Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentDebateCreate(BaseModel):
    objective: str = Field(..., min_length=10, max_length=2000)
    context: dict[str, Any] | None = None


class AgentDebateUpdate(BaseModel):
    objective: str | None = Field(default=None, min_length=10, max_length=2000)
    status: str | None = None


class AgentDebateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    objective: str
    status: str
    manager_agent_id: str | None
    context: dict[str, Any] | None
    final_synthesis: str | None
    recommendation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AgentDebateListResponse(BaseModel):
    debates: list[AgentDebateResponse]


class AgentTaskCreate(BaseModel):
    assigned_to: str  # marketing, product, designer, software
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    input_data: dict[str, Any] | None = None


class AgentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    debate_id: uuid.UUID
    merchant_id: uuid.UUID
    assigned_to: str
    title: str
    description: str | None
    status: str
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    error: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentTaskListResponse(BaseModel):
    tasks: list[AgentTaskResponse]


class AgentFindingCreate(BaseModel):
    task_id: uuid.UUID | None = None
    agent_specialty: str  # marketing, product, designer, software
    finding_type: str  # supporting, opposing, neutral, uncertainty
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    evidence: list[Any] | None = None
    confidence: float = Field(..., ge=0, le=1)
    uncertainty_notes: str | None = None
    supports_recommendation: bool | None = None


class AgentFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    debate_id: uuid.UUID
    task_id: uuid.UUID | None
    merchant_id: uuid.UUID
    agent_specialty: str
    finding_type: str
    title: str
    description: str | None
    evidence: list[Any] | None
    confidence: float
    uncertainty_notes: str | None
    supports_recommendation: bool | None
    created_at: datetime
    updated_at: datetime


class AgentFindingListResponse(BaseModel):
    findings: list[AgentFindingResponse]


class AgentMessageCreate(BaseModel):
    from_agent: str  # marketing, product, designer, software, manager
    to_agent: str | None = None
    message_type: str  # question, response, challenge, synthesis
    content: str = Field(..., min_length=1)
    references: list[Any] | None = None


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    debate_id: uuid.UUID
    merchant_id: uuid.UUID
    from_agent: str
    to_agent: str | None
    message_type: str
    content: str
    references: list[Any] | None
    created_at: datetime
    updated_at: datetime


class AgentMessageListResponse(BaseModel):
    messages: list[AgentMessageResponse]


class AgentDebateSummaryResponse(BaseModel):
    debate_id: str
    objective: str
    status: str
    tasks: list[dict[str, Any]]
    findings_summary: dict[str, int]
    findings: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    final_synthesis: str | None


class AgentDebateSynthesizeRequest(BaseModel):
    synthesis: str | None = None


class AgentDebateConcludeRequest(BaseModel):
    synthesis: str
    recommendation_id: uuid.UUID | None = None