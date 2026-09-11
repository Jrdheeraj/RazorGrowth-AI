"""MarketingAGI API routes — the autonomous employee's control surface.

Final paths (after the single /api application prefix):

  GET  /api/marketing-agi/status          — analyst+ : agent capabilities & integrations
  GET  /api/marketing-agi/runs            — analyst+ : run history (tenant-scoped)
  GET  /api/marketing-agi/runs/{id}       — analyst+ : one run with full brain state
  POST /api/marketing-agi/runs            — operator+ : start an autonomous run
  POST /api/marketing-agi/runs/{id}/cancel — operator+ : request cancellation
  GET  /api/marketing-agi/runs/{id}/events?after_seq=N — analyst+ : REAL event stream (poll)
  GET  /api/marketing-agi/campaigns       — analyst+ : campaign workspace
  GET  /api/marketing-agi/learnings       — analyst+ : learning history
  GET  /api/marketing-agi/handoffs        — analyst+ : specialist handoffs

Approval/execution intentionally DO NOT exist here: they go through the
existing human-only /api/actions endpoints. The MarketingAGI can never
approve its own actions.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.core.config import get_settings
from backend.app.db.session import get_db, get_session_factory
from backend.app.schemas.marketing_agi import (
    AGICampaignListResponse,
    AGICampaignResponse,
    AGIEventsResponse,
    AGIHandoffListResponse,
    AGIHandoffResponse,
    AGILearningListResponse,
    AGILearningResponse,
    AGIRunEvent,
    AGIRunListResponse,
    AGIRunResponse,
    AGIStartRequest,
    AGIStartResponse,
    AGIStatusResponse,
    AGIToolCatalogResponse,
    AGIWorkflowCatalogResponse,
)
from backend.app.agents.marketing_agi.agent import MarketingAGI
from backend.app.agents.marketing_agi.events import list_events, serialize_event
from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
from backend.app.agents.marketing_agi.tools.registry import get_registry
from backend.app.agents.marketing_agi.workflows import workflow_catalog
from backend.app.agents.marketing_agi.memory import MarketingAGILearningStore
from backend.app.agents.marketing_agi.handoff import HandoffInterface, serialize_handoff
from backend.app.models.marketing_agi import (
    MarketingAGICampaign,
    MarketingAGIRun,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing-agi", tags=["marketing-agi"])


# ---------------------------------------------------------------------------
# Provider builders (mirror existing route patterns; 503 when unconfigured)
# ---------------------------------------------------------------------------


def _build_llm() -> BaseLLMProvider | None:
    """Build the LLM from settings; None when not configured (agent still
    runs deterministically — honest, not fake)."""
    settings = get_settings()
    if settings.LLM_PROVIDER.lower() == "groq":
        api_key, model = settings.GROQ_API_KEY, settings.GROQ_MODEL
    else:
        api_key, model = settings.LLM_API_KEY, settings.LLM_MODEL
    if not api_key:
        return None
    from backend.app.ai.llm.provider import build_llm_provider

    return build_llm_provider(
        provider=settings.LLM_PROVIDER,
        api_key=api_key,
        model=model,
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        max_tokens=settings.LLM_MAX_TOKENS,
    )


def _build_embedder():
    settings = get_settings()
    if not settings.LLM_API_KEY:
        return None
    from backend.app.ai.embeddings.provider import build_embedding_provider

    return build_embedding_provider(
        provider=settings.EMBEDDING_PROVIDER,
        api_key=settings.LLM_API_KEY,
        model=settings.EMBEDDING_MODEL,
    )


def _llm_identity() -> tuple[bool, str | None, str | None]:
    settings = get_settings()
    if settings.LLM_PROVIDER.lower() == "groq":
        configured = bool(settings.GROQ_API_KEY)
        model = settings.GROQ_MODEL
    else:
        configured = bool(settings.LLM_API_KEY)
        model = settings.LLM_MODEL
    return configured, settings.LLM_PROVIDER if configured else None, model if configured else None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_run(run: MarketingAGIRun) -> dict[str, Any]:
    state = run.state or {}
    return {
        "id": str(run.id),
        "merchant_id": str(run.merchant_id),
        "objective": run.objective,
        "status": run.status,
        "phase": run.phase,
        "iterations": run.iterations,
        "tool_call_count": run.tool_call_count,
        "started_at": str(run.started_at) if run.started_at else None,
        "completed_at": str(run.completed_at) if run.completed_at else None,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "state": {
            "objective": state.get("objective"),
            "observations": state.get("observations", []),
            "hypotheses": state.get("hypotheses", []),
            "knowledge_gaps": state.get("knowledge_gaps", []),
            "evidence": state.get("evidence", []),
            "retrieval_log": state.get("retrieval_log", []),
            "tool_calls": state.get("tool_calls", []),
            "workflow": state.get("workflow"),
            "plan": state.get("plan", []),
            "campaign_draft": state.get("campaign_draft"),
            "verification": state.get("verification"),
            "prepared_action": state.get("prepared_action"),
            "iterations": state.get("iterations", run.iterations),
            "tool_call_count": state.get("tool_call_count", run.tool_call_count),
            "duplicate_tool_calls": state.get("duplicate_tool_calls", 0),
            "errors": state.get("errors", []),
        },
        "result": run.result,
        "errors": run.errors or [],
    }


def _serialize_campaign(c: MarketingAGICampaign) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "run_id": str(c.run_id) if c.run_id else None,
        "campaign_key": c.campaign_key,
        "workflow": c.workflow,
        "name": c.name,
        "objective": c.objective,
        "channel": c.channel,
        "integration_status": c.integration_status,
        "lifecycle": c.lifecycle,
        "audience_count": c.audience_count,
        "audience": c.audience,
        "content": c.content,
        "expected_impact": c.expected_impact,
        "estimated_revenue_inr": float(c.estimated_revenue) if c.estimated_revenue else None,
        "success_metric": c.success_metric,
        "evidence_refs": c.evidence_refs or [],
        "verification": c.verification,
        "action_id": str(c.action_id) if c.action_id else None,
        "created_at": str(c.created_at),
    }


# ---------------------------------------------------------------------------
# Background worker (runs the loop off the request thread, like debates)
# ---------------------------------------------------------------------------


def _run_agi_worker(run_id: uuid.UUID, merchant_id: uuid.UUID, objective: str) -> None:
    db = get_session_factory()()
    try:
        run_row = db.get(MarketingAGIRun, run_id)
        if run_row is None or run_row.merchant_id != merchant_id:
            log.error("AGI worker: run %s not found for merchant", run_id)
            return
        llm = _build_llm()
        embedder = _build_embedder()
        agent = MarketingAGI(db, merchant_id, llm=llm, embedding_provider=embedder)
        agent.run(run_row, objective)
    except Exception:
        log.exception("MarketingAGI worker crashed for run %s", run_id)
        db.rollback()
        try:
            run_row = db.get(MarketingAGIRun, run_id)
            if run_row is not None and run_row.status in {"queued", "running"}:
                from datetime import datetime, timezone

                run_row.status = "failed"
                run_row.completed_at = datetime.now(timezone.utc)
                run_row.errors = ["worker_crashed"]
                db.commit()
        except Exception:
            log.error("Could not persist failure state for run %s", run_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AGIStatusResponse)
def agi_status(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Agent capability + integration transparency."""
    register_all_tools()
    registry = get_registry()
    llm_configured, provider, model = _llm_identity()
    integration_map: dict[str, str] = {}
    for tool in registry.catalog():
        cat = tool["category"]
        if cat == "integrations":
            integration_map[tool["name"]] = tool["integration_status"]
    return {
        "llm_configured": llm_configured,
        "llm_provider": provider,
        "llm_model": model,
        "integration_status": {
            "email_marketing": "draft_only",
            "google_ads": "requires_integration",
            "meta_ads": "requires_integration",
            "social_platforms": "requires_integration",
            **integration_map,
        },
        "tools_available": len(registry.catalog()),
        "workflows_available": len(workflow_catalog()),
    }


@router.get("/tools", response_model=AGIToolCatalogResponse)
def tool_catalog(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    register_all_tools()
    return {"tools": get_registry().catalog()}


@router.get("/workflows", response_model=AGIWorkflowCatalogResponse)
def workflow_catalog_route(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    return {"workflows": workflow_catalog()}


@router.post("/runs", response_model=AGIStartResponse, status_code=202)
def start_run(
    request: AGIStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Start an autonomous MarketingAGI run (operator+).

    The loop runs in the background; the frontend polls events.
    """
    llm_configured, provider, model = _llm_identity()
    run_row = MarketingAGIRun(
        merchant_id=ctx.merchant_id,
        objective=request.objective,
        status="queued",
        phase="load_context",
        llm_provider=provider,
        llm_model=model,
    )
    db.add(run_row)
    db.commit()
    background_tasks.add_task(
        _run_agi_worker, run_row.id, ctx.merchant_id, request.objective
    )
    return {
        "run_id": str(run_row.id),
        "status": run_row.status,
        "objective": run_row.objective,
    }


@router.get("/runs", response_model=AGIRunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    stmt = (
        select(MarketingAGIRun)
        .where(MarketingAGIRun.merchant_id == ctx.merchant_id)
        .order_by(MarketingAGIRun.created_at.desc())
        .limit(limit)
    )
    runs = list(db.scalars(stmt).all())
    return {"runs": [_serialize_run(r) for r in runs]}


@router.get("/runs/{run_id}", response_model=AGIRunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    run = db.get(MarketingAGIRun, rid)
    if run is None or run.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return _serialize_run(run)


@router.post("/runs/{run_id}/cancel", response_model=AGIRunResponse)
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    run = db.get(MarketingAGIRun, rid)
    if run is None or run.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    if run.status in {"queued", "running"}:
        # cooperative cancellation: the loop checks state between phases
        state = run.state or {}
        state["cancelled"] = True
        run.state = state
        db.commit()
    return _serialize_run(run)


@router.get("/runs/{run_id}/events", response_model=AGIEventsResponse)
def run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    run = db.get(MarketingAGIRun, rid)
    if run is None or run.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    events = list_events(db, rid, ctx.merchant_id, after_seq=after_seq)
    return {
        "run_id": run_id,
        "events": [serialize_event(e) for e in events],
    }


@router.get("/campaigns", response_model=AGICampaignListResponse)
def list_campaigns(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    stmt = (
        select(MarketingAGICampaign)
        .where(MarketingAGICampaign.merchant_id == ctx.merchant_id)
        .order_by(MarketingAGICampaign.created_at.desc())
        .limit(50)
    )
    rows = list(db.scalars(stmt).all())
    return {"campaigns": [_serialize_campaign(c) for c in rows]}


@router.get("/learnings", response_model=AGILearningListResponse)
def list_learnings(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    rows = MarketingAGILearningStore(db).list_learnings(ctx.merchant_id, limit=20)
    return {
        "learnings": [
            {
                "id": str(r.id),
                "campaign_id": str(r.campaign_id) if r.campaign_id else None,
                "action_id": str(r.action_id) if r.action_id else None,
                "status": r.status,
                "expected": r.expected,
                "actual": r.actual,
                "verdict": r.verdict,
                "insights": r.insights,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    }


@router.get("/handoffs", response_model=AGIHandoffListResponse)
def list_handoffs(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    rows = HandoffInterface(db).list_handoffs(ctx.merchant_id, limit=20)
    return {"handoffs": [serialize_handoff(h) for h in rows]}
