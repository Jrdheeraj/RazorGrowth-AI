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
    AgentDashboardResponse,
    AgentDashboardAgent,
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
    DebateRoundAdvanceRequest,
    DebateRoundResponse,
    DebateRoundStatus,
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


# ─────────────────────────────────────────────────────────────────────────────
# Debate Rounds (Task 7)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{debate_id}/rounds", response_model=DebateRoundStatus)
def get_debate_rounds(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get current debate round status with all rounds and agent positions."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    return svc.get_debate_round_status(did)


@router.post("/{debate_id}/rounds/advance", response_model=DebateRoundStatus)
def advance_debate_round(
    debate_id: str,
    payload: DebateRoundAdvanceRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Advance the debate to the next round (operator+)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    if payload.target_round == 2:
        debate = svc.advance_to_round_2(did)
    elif payload.target_round == 3:
        debate = svc.advance_to_round_3(did)
    elif payload.target_round == 4:
        debate = svc.advance_to_synthesis(did)
    else:
        raise HTTPException(status_code=400, detail="Invalid target round. Must be 2, 3, or 4.")

    if not debate:
        raise HTTPException(status_code=400, detail="Cannot advance debate round")

    db.commit()
    return svc.get_debate_round_status(did)


@router.get("/{debate_id}/round/{round_number}/positions", response_model=dict[str, Any])
def get_round_agent_positions(
    debate_id: str,
    round_number: int,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get all agent positions for a specific debate round."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    if round_number not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Invalid round number. Must be 1, 2, or 3.")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    # Get all findings and messages for this round
    findings = svc._finding_repo.list_by_debate(did)
    messages = svc._message_repo.list_by_debate(did)

    # Filter for this round (based on message round or finding round)
    round_findings = [f for f in findings if getattr(f, 'round', 1) == round_number]
    round_messages = [m for m in messages if getattr(m, 'round', 1) == round_number]

    # Group by agent
    positions = {}
    for f in round_findings:
        agent = f.agent_specialty
        if agent not in positions:
            positions[agent] = {"findings": [], "messages": []}
        positions[agent]["findings"].append({
            "type": f.finding_type.value,
            "title": f.title,
            "description": f.description,
            "confidence": float(f.confidence),
            "supports_recommendation": f.supports_recommendation,
        })

    for m in round_messages:
        agent = m.from_agent
        if agent not in positions:
            positions[agent] = {"findings": [], "messages": []}
        positions[agent]["messages"].append({
            "type": m.message_type,
            "content": m.content,
            "to": m.to_agent,
        })

    return {
        "round": round_number,
        "positions": positions,
    }


@router.post("/{debate_id}/round/1/complete", response_model=DebateRoundStatus)
def complete_round_1(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Mark Round 1 (independent analysis) as complete and advance to Round 2."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.advance_to_round_2(did)
    if not debate:
        raise HTTPException(status_code=400, detail="Cannot advance to Round 2")

    db.commit()
    return svc.get_debate_round_status(did)


@router.post("/{debate_id}/round/2/complete", response_model=DebateRoundStatus)
def complete_round_2(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Mark Round 2 (cross-agent debate) as complete and advance to Round 3."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.advance_to_round_3(did)
    if not debate:
        raise HTTPException(status_code=400, detail="Cannot advance to Round 3")

    db.commit()
    return svc.get_debate_round_status(did)


@router.post("/{debate_id}/round/3/complete", response_model=DebateRoundStatus)
def complete_round_3(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Mark Round 3 (rebuttals) as complete and advance to synthesis."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.advance_to_synthesis(did)
    if not debate:
        raise HTTPException(status_code=400, detail="Cannot advance to synthesis")

    db.commit()
    return svc.get_debate_round_status(did)


# ─────────────────────────────────────────────────────────────────────────────
# Agent Dashboard
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{debate_id}/dashboard", response_model=AgentDashboardResponse)
def get_agent_dashboard(
    debate_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get the complete agent dashboard for a debate (tenant-isolated)."""
    try:
        did = uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate_id format")

    svc = AgentDebateService(db)
    debate = svc.get_debate(did)
    if not debate or debate.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="DEBATE_NOT_FOUND")

    # Get all tasks, findings, and messages
    tasks = svc.list_tasks_by_debate(did)
    findings = svc.list_findings_by_debate(did)
    messages = svc.list_messages_by_debate(did)

    # Map findings by agent specialty
    findings_by_agent: dict[str, list] = {}
    for f in findings:
        specialty = f.agent_specialty
        if specialty not in findings_by_agent:
            findings_by_agent[specialty] = []
        findings_by_agent[specialty].append(f)

    # Agent specialty metadata
    agent_meta = {
        "marketing": {"name": "MarketingAgent", "description": "Audience analysis, segmentation, retention, campaigns"},
        "product": {"name": "ProductAgent", "description": "Upsell, cross-sell, product affinity, experimentation"},
        "designer": {"name": "DesignerAgent", "description": "Creative concepts, messaging, experiment variants, UX"},
        "software": {"name": "SoftwareAgent", "description": "Technical architecture, integrations, automation, feasibility"},
        "manager": {"name": "ManagerAgent", "description": "Coordination, task delegation, synthesis, debate orchestration"},
    }

    # Build agent dashboard entries
    agents_dashboard = []
    for specialty, meta in agent_meta.items():
        task = next((t for t in tasks if t.assigned_to == specialty), None)
        agent_findings = findings_by_agent.get(specialty, [])
        
        supporting = len([f for f in agent_findings if f.finding_type == FindingType.supporting])
        opposing = len([f for f in agent_findings if f.finding_type == FindingType.opposing])
        uncertainty = len([f for f in agent_findings if f.finding_type == FindingType.uncertainty])
        neutral = len([f for f in agent_findings if f.finding_type == FindingType.neutral])
        
        confidences = [float(f.confidence) for f in agent_findings if f.confidence is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else None
        
        # Determine status
        if task:
            status = task.status.value
        elif agent_findings:
            status = "completed"
        else:
            status = "pending"
        
        # Build evidence summary from findings
        evidence_sources = set()
        for f in agent_findings:
            if f.evidence:
                for e in f.evidence:
                    if isinstance(e, dict) and "source" in e:
                        evidence_sources.add(e["source"])
                    elif isinstance(e, dict) and "type" in e:
                        evidence_sources.add(e["type"])
        
        agents_dashboard.append(AgentDashboardAgent(
            specialty=specialty,
            name=meta["name"],
            description=meta["description"],
            status=status,
            task_id=task.id if task else None,
            findings_count=len(agent_findings),
            supporting_findings=supporting,
            opposing_findings=opposing,
            uncertainty_findings=uncertainty,
            confidence_avg=round(avg_confidence, 3) if avg_confidence else None,
            evidence_summary={"sources": list(evidence_sources)} if evidence_sources else None,
            output_summary=task.output_data if task else None,
        ))

    # Aggregate findings by type
    findings_by_type = {
        "supporting": len([f for f in findings if f.finding_type == FindingType.supporting]),
        "opposing": len([f for f in findings if f.finding_type == FindingType.opposing]),
        "neutral": len([f for f in findings if f.finding_type == FindingType.neutral]),
        "uncertainty": len([f for f in findings if f.finding_type == FindingType.uncertainty]),
    }

    # Extract recommendation from synthesis
    recommendation = None
    if debate.final_synthesis and "Manager Recommendation:" in debate.final_synthesis:
        try:
            recommendation = debate.final_synthesis.split("Manager Recommendation:")[-1].strip()
        except Exception:
            pass

    return AgentDashboardResponse(
        debate_id=debate.id,
        objective=debate.objective,
        debate_status=debate.status.value,
        rag_context=debate.context.get("rag_context") if debate.context else None,
        agents=agents_dashboard,
        total_findings=len(findings),
        findings_by_type=findings_by_type,
        final_synthesis=debate.final_synthesis,
        recommendation=recommendation,
    )