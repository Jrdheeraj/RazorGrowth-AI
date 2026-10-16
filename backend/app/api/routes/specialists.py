"""
Specialist workspace APIs for the existing AI Team dashboard.

This router deliberately does NOT create a new dashboard. It feeds the
already-existing AI Team page the real state it needs to manage every
in-scope specialist:

  GET  /api/agents/catalog                      registry-driven tool catalog
  POST /api/agents/{agent_name}/run             launch ONE specialist
  GET  /api/agents/handoffs                     persisted cross-agent handoffs
  POST /api/agents/handoffs/{id}/dispatch       actually dispatch a handoff
  GET  /api/personalization/decisions           real next-best-action decisions

Everything returned here is real backend state. Nothing is synthesised,
stubbed or defaulted to a plausible-looking value.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    MerchantContext,
    merchant_ctx,
    operator_ctx,
    resolve_claimed_merchant,
)
from backend.app.core.config import get_settings
from backend.app.db.session import get_db
from backend.app.schemas.phase5 import SingleAgentRunRequest

log = logging.getLogger(__name__)
router = APIRouter(tags=["specialists"])


@router.get("/agents/catalog")
def list_agent_tool_catalog(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    The canonical tool catalog.

    Returns every advertised capability with its schemas, permission
    requirement and implementing service. Agents whose declared tool names
    have no implementation are reported under ``unimplemented_tools`` instead
    of being presented to the merchant as real capabilities.
    """
    from backend.app.agents.catalog import catalog_payload
    from backend.app.agents.registry import agent_catalog

    tools = catalog_payload()
    agents = agent_catalog()
    return {
        "tools": tools,
        "tool_count": len(tools),
        "agents": [
            {
                "name": e["name"],
                "description": e["description"],
                "category": e["category"],
                "permissions": e["permissions"],
                "tools": e["tools"],
                "unimplemented_tools": e["unimplemented_tools"],
                "tool_details": e["tool_details"],
                "can_approve": e["can_approve"],
                "can_execute": e["can_execute"],
            }
            for e in agents
        ],
        "agent_count": len(agents),
    }


@router.post("/agents/{agent_name}/run")
def run_single_agent(
    agent_name: str,
    request: SingleAgentRunRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Launch ONE registered specialist from the AI Team workspace.

    Runs synchronously through the ordinary agent protocol, so the agent
    receives its permission checks, savepoint failure isolation and
    structured result exactly as it would inside the orchestrator. A real
    AgentRun row is written so the run appears in run history.

    Operators and above only. Nothing here can approve or execute an action.
    """
    from backend.app.agents.base import AgentContext, AgentResult
    from backend.app.agents.registry import AGENT_INSTANCES
    from backend.app.services.agent_run_service import AgentRunService

    agent = AGENT_INSTANCES.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")

    merchant_id = resolve_claimed_merchant(ctx, request.merchant_id)
    settings = get_settings()

    llm = None
    from backend.app.ai.llm.provider import resolve_llm_provider

    resolved = resolve_llm_provider(settings)
    if resolved is not None:
        llm = resolved.build(
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    params = dict(request.params or {})
    params.setdefault("phase", "work")

    runs = AgentRunService(db)
    run_row = runs.start_run(
        merchant_id=merchant_id,
        agent_name=agent.NAME,
        orchestrator_run_id=request.correlation_id,
        mode="single",
        input_summary={"params": params},
    )

    agent_ctx = AgentContext(
        db=db,
        merchant_id=merchant_id,
        mode="single",
        params=params,
        llm=llm,
        embedding_provider=None,
    )

    savepoint = db.begin_nested()
    try:
        result: AgentResult = agent.execute(agent_ctx)
        savepoint.commit()
    except Exception as exc:
        savepoint.rollback()
        log.exception("Single agent run failed for %s", agent_name)
        result = AgentResult(agent_name=agent.NAME, status="failed")
        result.errors.append(f"{type(exc).__name__}: {exc}")

    try:
        runs.complete_run(run_row, result)
    except Exception:
        log.exception("Failed to persist AgentRun for %s", agent_name)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="AGENT_RUN_COMMIT_FAILED")

    return {
        "agent": result.agent_name,
        "status": result.status,
        "ok": result.ok,
        "output": result.output,
        "errors": result.errors,
        "tools_used": result.tools_used,
        "opportunities_created": result.opportunities_created,
        "actions_proposed": result.actions_proposed,
        "insights_generated": result.insights_generated,
        "signals_detected": result.signals_detected,
        "experiments_proposed": result.experiments_proposed,
        "latency_ms": {
            "total": result.total_ms,
            "llm": result.llm_ms,
            "db": result.db_ms,
        },
        "llm_configured": llm is not None,
    }


@router.get("/agents/handoffs")
def list_agent_handoffs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Persisted cross-agent handoffs for this merchant (tenant-scoped)."""
    from backend.app.services.handoff import handoff_service

    return {
        "handoffs": handoff_service.history(db, ctx.merchant_id, limit=limit)
    }


@router.post("/agents/handoffs/{handoff_id}/dispatch")
def dispatch_agent_handoff(
    handoff_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Actually dispatch a pending handoff and persist its verified outcome.

    The destination agent really executes. A completed handoff is never
    dispatched twice, and a handoff belonging to another workspace is
    reported as not found.
    """
    from backend.app.services.handoff import HandoffError, handoff_service

    try:
        outcome = handoff_service.dispatch(
            db, merchant_id=ctx.merchant_id, handoff_id=handoff_id
        )
    except HandoffError:
        raise HTTPException(status_code=404, detail="HANDOFF_NOT_FOUND")

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="HANDOFF_DISPATCH_FAILED")

    return outcome


@router.get("/personalization/decisions")
def list_personalization_decisions(
    limit: int = Query(default=100, ge=1, le=500),
    cohort: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Real per-customer next-best-action decisions plus honest measurement."""
    from backend.app.services.personalization import PersonalizationService

    svc = PersonalizationService(db)
    return {
        "decisions": svc.list_decisions(ctx.merchant_id, limit=limit, cohort=cohort),
        "measurement": svc.measure_outcomes(ctx.merchant_id),
    }


__all__ = ["router"]