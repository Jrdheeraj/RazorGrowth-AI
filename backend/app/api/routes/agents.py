"""Agent observability + orchestration APIs — Phase 5 Feature 21.

Endpoints (final paths after the single /api application prefix):
  GET  /api/agents
  GET  /api/agents/runs
  GET  /api/agents/runs/{run_id}
  POST /api/agents/run

The POST endpoint drives GrowthAgentOrchestrator. It can only CREATE
proposals — approval and execution remain Phase 4 human-only operations.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.agents.orchestrator import (
    GrowthAgentOrchestrator,
    MerchantNotFoundError,
)
from backend.app.agents.registry import agent_catalog
from backend.app.core.config import get_settings
from backend.app.db.session import get_db
from backend.app.schemas.phase5 import (
    AgentRunRecord,
    AgentRunRequest,
    AgentRunsResponse,
    AgentsListResponse,
    OrchestratorRunResponse,
)
from backend.app.services.agent_run_service import AgentRunService

log = logging.getLogger(__name__)
router = APIRouter(tags=["agents"])


def _resolve_merchant(db: Session, merchant_id: uuid.UUID | None) -> uuid.UUID:
    if merchant_id is not None:
        from backend.app.models.merchant import Merchant

        if db.get(Merchant, merchant_id) is None:
            raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
        return merchant_id
    from backend.app.repositories.merchant import MerchantRepository

    merchants = MerchantRepository(db).list_all(limit=1)
    if not merchants:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    return merchants[0].id


@router.get("/agents", response_model=AgentsListResponse)
def list_agents(db: Session = Depends(get_db)) -> Any:
    """Agent registry with capability transparency (Feature 13/15)."""
    runs = AgentRunService(db)
    return {
        "agents": agent_catalog(),
        "observability": runs.observability_summary(),
    }


@router.get("/agents/runs", response_model=AgentRunsResponse)
def list_agent_runs(
    merchant_id: uuid.UUID | None = None,
    orchestrator_run_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Any:
    claimed_mid = _resolve_merchant(db, merchant_id)
    runs = AgentRunService(db).list_runs(
        claimed_mid,
        orchestrator_run_id=orchestrator_run_id,
        limit=limit,
    )

    def _record(run: Any) -> dict[str, Any]:
        return {
            "id": str(run.id),
            "merchant_id": str(run.merchant_id) if run.merchant_id else None,
            "agent_name": run.agent_name,
            "status": str(getattr(run.status, "value", run.status)),
            "mode": run.mode,
            "started_at": str(run.started_at),
            "completed_at": str(run.completed_at) if run.completed_at else None,
            "total_latency_ms": run.total_latency_ms,
            "llm_latency_ms": run.llm_latency_ms,
            "db_latency_ms": run.db_latency_ms,
            "tool_latency_ms": run.tool_latency_ms,
            "opportunities_created": run.opportunities_created,
            "actions_proposed": run.actions_proposed,
            "llm_provider": run.llm_provider,
            "llm_model": run.llm_model,
            "tools_used": run.tools_used,
            "errors": run.errors,
        }

    return {"runs": [_record(r) for r in runs]}


@router.get("/agents/runs/{run_id}", response_model=AgentRunRecord)
def get_agent_run(
    run_id: str,
    merchant_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> Any:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    claimed_mid = _resolve_merchant(db, merchant_id)
    run = AgentRunService(db).get_run(rid, merchant_id=claimed_mid)
    if run is None:
        # either nonexistent or owned by another merchant — same answer (no leak)
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return {
        "id": str(run.id),
        "merchant_id": str(run.merchant_id) if run.merchant_id else None,
        "agent_name": run.agent_name,
        "status": str(getattr(run.status, "value", run.status)),
        "mode": run.mode,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at) if run.completed_at else None,
        "total_latency_ms": run.total_latency_ms,
        "llm_latency_ms": run.llm_latency_ms,
        "db_latency_ms": run.db_latency_ms,
        "tool_latency_ms": run.tool_latency_ms,
        "opportunities_created": run.opportunities_created,
        "actions_proposed": run.actions_proposed,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "tools_used": run.tools_used,
        "errors": run.errors,
    }


@router.post("/agents/run", response_model=OrchestratorRunResponse)
def run_agents(request: AgentRunRequest, db: Session = Depends(get_db)) -> Any:
    """
    Trigger a controlled orchestration run.

    Produces opportunities/signals/proposals only. Nothing executes and
    nothing is approved without a human (Phase 4 invariants preserved).
    """
    if request.mode not in ("fast", "deep"):
        raise HTTPException(status_code=422, detail="mode must be 'fast' or 'deep'")
    merchant_id = _resolve_merchant(db, request.merchant_id)

    settings = get_settings()
    llm = None
    api_key = (
        settings.GROQ_API_KEY
        if settings.LLM_PROVIDER.lower() == "groq"
        else settings.LLM_API_KEY
    )
    if request.mode == "deep" and api_key:
        from backend.app.ai.llm.provider import build_llm_provider

        llm = build_llm_provider(
            provider=settings.LLM_PROVIDER,
            api_key=api_key,
            model=(
                settings.GROQ_MODEL
                if settings.LLM_PROVIDER.lower() == "groq"
                else settings.LLM_MODEL
            ),
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    from backend.app.agents.orchestrator import GrowthAgentOrchestrator as _GAO

    orchestrator = _GAO(
        db, llm=llm, embedding_provider=None
    )
    params = {
        "window_days": request.window_days,
        "propose_retry_action": request.propose_actions,
    }
    try:
        summary = orchestrator.run(merchant_id, mode=request.mode, params=params)
    except MerchantNotFoundError:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    except Exception as exc:  # central safety net; log details server-side only
        log.exception("Orchestration failed")
        raise HTTPException(status_code=500, detail="AGENT_RUN_FAILED")

    try:
        db.commit()
    except Exception as exc:
        log.warning("Failed to commit orchestration results: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="AGENT_RUN_COMMIT_FAILED")

    return summary.to_dict()
