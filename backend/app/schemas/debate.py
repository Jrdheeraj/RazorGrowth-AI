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


class AgentDebateChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


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


# ─── Debate Rounds ──────────────────────────────────────────────────────────


class DebateRound(BaseModel):
    round_number: int
    name: str
    description: str
    status: str  # pending, active, completed
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DebateRoundStatus(BaseModel):
    debate_id: uuid.UUID
    current_round: int
    max_rounds: int = 4
    status: str  # initiated, investigating, debating, rebuttal, synthesizing, concluded
    rounds: list[DebateRound]
    current_round_status: str  # pending, active, completed


class DebateRoundAdvanceRequest(BaseModel):
    target_round: int = Field(..., ge=2, le=4)


class DebateRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    debate_id: uuid.UUID
    current_round: int
    status: str
    round_details: dict[int, dict[str, Any]]
    agent_positions: dict[str, dict[str, Any]]


# ─── Agent Dashboard ──────────────────────────────────────────────────────────


class AgentDashboardAgent(BaseModel):
    """Agent info for dashboard display."""
    specialty: str
    name: str
    description: str
    status: str  # pending, running, completed, failed
    task_id: uuid.UUID | None = None
    findings_count: int = 0
    supporting_findings: int = 0
    opposing_findings: int = 0
    uncertainty_findings: int = 0
    confidence_avg: float | None = None
    evidence_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None


class AgentDashboardResponse(BaseModel):
    """Complete agent dashboard for a debate."""
    debate_id: uuid.UUID
    objective: str
    debate_status: str
    rag_context: dict[str, Any] | None = None
    agents: list[AgentDashboardAgent]
    total_findings: int = 0
    findings_by_type: dict[str, int] = {}
    final_synthesis: str | None = None
    recommendation: str | None = None