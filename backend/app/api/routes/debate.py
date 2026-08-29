"""Agent Debate API routes — Phase F."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx, approver_ctx
from backend.app.db.session import get_db
from backend.app.models.enums import AgentSpecialty, DebateStatus, FindingType, TaskStatus
from backend.app.schemas.debate import (
    AgentDebateCreate,
    AgentDebateListResponse,
    AgentDebateResponse,
    AgentDebateSummaryResponse,
    AgentDebateUpdate,
    AgentDebateConcludeRequest,
    AgentFindingCreate,
    AgentFindingListResponse,
    AgentFindingResponse,
    AgentMessageCreate,
    AgentMessageListResponse,
    AgentMessageResponse,
    AgentTaskCreate,
    AgentTaskListResponse,
    AgentTaskResponse,
)
from backend.app.services.agent_debate_service import AgentDebateService

router = APIRouter(prefix="/agent-debates", tags=["agent-debates"])


# ─────────────────────────────────────────────────────────────────────────────
# Debate CRUD
# ─────────────────────────────────────────────────────────────────────────────


@router.post("", response_model=AgentDebateResponse, status_code=201)
def create_debate(
    payload: AgentDebateCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a new agent debate session (operator+)."""
    svc = AgentDebateService(db)
    debate = svc.create_debate(
        merchant_id=ctx.merchant_id,
        objective=payload.objective,
        manager_agent_id="ManagerAgent",
        context=payload.context,
    )
    db.commit()
    return AgentDebateResponse.model_validate(debate, from_attributes=True)


@router.get("", response_model=AgentDebateListResponse)
def list_debates(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List debates for the caller's merchant (tenant-isolated)."""
    status_enum = DebateStatus(status) if status else None
    svc = AgentDebateService(db)
    debates = svc.list_debates(
        ctx.merchant_id, status=status_enum, limit=limit, offset=offset
    )
    return {
        "debates": [
            AgentDebateResponse.model_validate(d, from_attributes=True) for d in debates
        ]
    }


@router.get("/{debate_id}", response_model=AgentDebateResponse)
def get_debate(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single debate by ID (tenant-isolated)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    return AgentDebateResponse.model_validate(debate, from_attributes=True)


@router.patch("/{debate_id}", response_model=AgentDebateResponse)
def update_debate(
    debate_id: str,
    payload: AgentDebateUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Update a debate (operator+)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    if payload.objective is not None:
        debate.objective = payload.objective
    if payload.status is not None:
        debate.status = DebateStatus(payload.status)
    db.commit()

    return AgentDebateResponse.model_validate(debate, from_attributes=True)


@router.get("/{debate_id}/summary", response_model=AgentDebateSummaryResponse)
def get_debate_summary(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a structured summary of the debate for synthesis."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    summary = svc.get_debate_summary(did)
    if not summary:
        raise HTTPException(status_code=404, detail="DEBATE_SUMMARY_EMPTY")

    return summary


@router.post("/{debate_id}/conclude", response_model=AgentDebateResponse)
def conclude_debate(
    debate_id: str,
    payload: AgentDebateConcludeRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Conclude a debate with synthesis (owner/admin only)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    if debate.status == DebateStatus.concluded:
        raise HTTPException(status_code=400, detail="DEBATE_ALREADY_CONCLUDED")

    debate = svc.set_debate_synthesis(did, payload.synthesis)
    if payload.recommendation_id:
        debate = svc.link_recommendation(did, payload.recommendation_id)
    db.commit()

    return AgentDebateResponse.model_validate(debate, from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Task management
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{debate_id}/tasks", response_model=AgentTaskResponse, status_code=201)
def create_task(
    debate_id: str,
    payload: AgentTaskCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a task for a specialist agent (operator+)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    try:
        assigned_to = AgentSpecialty(payload.assigned_to)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid assigned_to. Must be one of: {[s.value for s in AgentSpecialty]}",
        )

    task = svc.create_task(
        debate_id=did,
        merchant_id=ctx.merchant_id,
        assigned_to=assigned_to,
        title=payload.title,
        description=payload.description,
        input_data=payload.input_data,
    )
    db.commit()
    return AgentTaskResponse.model_validate(task, from_attributes=True)


@router.get("/{debate_id}/tasks", response_model=AgentTaskListResponse)
def list_tasks(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List tasks for a debate (tenant-isolated)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    tasks = svc.list_tasks_by_debate(did)
    return {
        "tasks": [AgentTaskResponse.model_validate(t, from_attributes=True) for t in tasks]
    }


@router.get("/{debate_id}/tasks/{task_id}", response_model=AgentTaskResponse)
def get_task(
    debate_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single task by ID."""
    try:
        did = uuid.UUID(debate_id)
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    task = svc.get_task(tid)
    if not task or task.debate_id != did:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")

    return AgentTaskResponse.model_validate(task, from_attributes=True)


@router.post("/{debate_id}/tasks/{task_id}/complete", response_model=AgentTaskResponse)
def complete_task(
    debate_id: str,
    task_id: str,
    output_data: dict[str, Any] | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Complete a task with output or error (operator+)."""
    try:
        did = uuid.UUID(debate_id)
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    task = svc.complete_task(tid, output_data=output_data, error=error)
    if not task:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    db.commit()
    return AgentTaskResponse.model_validate(task, from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Finding management
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{debate_id}/findings", response_model=AgentFindingResponse, status_code=201)
def add_finding(
    debate_id: str,
    payload: AgentFindingCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Add a finding to a debate (operator+)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    try:
        finding_type = FindingType(payload.finding_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid finding_type. Must be one of: {[f.value for f in FindingType]}",
        )

    try:
        agent_specialty = AgentSpecialty(payload.agent_specialty)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent_specialty. Must be one of: {[s.value for s in AgentSpecialty]}",
        )

    task_id = uuid.UUID(payload.task_id) if payload.task_id else None

    finding = svc.add_finding(
        debate_id=did,
        merchant_id=ctx.merchant_id,
        task_id=task_id,
        agent_specialty=agent_specialty,
        finding_type=finding_type,
        title=payload.title,
        description=payload.description,
        evidence=payload.evidence,
        confidence=payload.confidence,
        uncertainty_notes=payload.uncertainty_notes,
        supports_recommendation=payload.supports_recommendation,
    )
    db.commit()
    return AgentFindingResponse.model_validate(finding, from_attributes=True)


@router.get("/{debate_id}/findings", response_model=AgentFindingListResponse)
def list_findings(
    debate_id: str,
    finding_type: str | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List findings for a debate (tenant-isolated)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    if finding_type:
        try:
            ft = FindingType(finding_type)
            findings = svc.list_findings_by_type(did, ft)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid finding_type. Must be one of: {[f.value for f in FindingType]}",
            )
    else:
        findings = svc.list_findings_by_debate(did)

    return {
        "findings": [
            AgentFindingResponse.model_validate(f, from_attributes=True) for f in findings
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# Message management
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{debate_id}/messages", response_model=AgentMessageResponse, status_code=201)
def add_message(
    debate_id: str,
    payload: AgentMessageCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Add a message to the debate (operator+)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    try:
        from_agent = AgentSpecialty(payload.from_agent)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid from_agent. Must be one of: {[s.value for s in AgentSpecialty]}",
        )

    to_agent = AgentSpecialty(payload.to_agent) if payload.to_agent else None

    message = svc.add_message(
        debate_id=did,
        merchant_id=ctx.merchant_id,
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=payload.message_type,
        content=payload.content,
        references=payload.references,
    )
    db.commit()
    return AgentMessageResponse.model_validate(message, from_attributes=True)


@router.get("/{debate_id}/messages", response_model=AgentMessageListResponse)
def list_messages(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List messages for a debate (tenant-isolated)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    messages = svc.list_messages_by_debate(did)
    return {
        "messages": [
            AgentMessageResponse.model_validate(m, from_attributes=True) for m in messages
        ]
    }