"""Product Agent API — the autonomous product-growth employee's control surface.

Final paths (after the single /api application prefix):

  GET  /api/product-agi/status                     — analyst+  : dashboard read model
  GET  /api/product-agi/catalog                    — analyst+  : real product rows + segments
  GET  /api/product-agi/platforms                  — analyst+  : honest connection states
  GET  /api/product-agi/runs                       — analyst+  : run history (tenant-scoped)
  POST /api/product-agi/runs                       — operator+ : start a run (returns immediately)
                                                      [the Product Agent normally starts from the
                                                       shared AI Team cycle; this endpoint joins an
                                                       in-flight run instead of duplicating it]
  GET  /api/product-agi/runs/{id}                  — analyst+  : one run with brain state
  POST /api/product-agi/runs/{id}/cancel           — operator+ : cooperative cancellation
  GET  /api/product-agi/runs/{id}/findings         — analyst+  : evidence-backed findings
  GET  /api/product-agi/runs/{id}/recommendations  — analyst+  : evidence-backed recommendations
  GET  /api/product-agi/runs/{id}/activity?after_seq=N — analyst+ : REAL event stream (poll)

Approval and execution intentionally DO NOT exist here. A recommendation
becomes an ``agent_actions`` row through ``action_service``; a human then
approves at ``POST /api/actions/{id}/approve``. The Product Agent can never
approve or execute its own work.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.agents.product_agi import service as pa_service
from backend.app.agents.product_agi.agent import ProductAGI
from backend.app.agents.product_agi.events import list_events, serialize_event
from backend.app.agents.product_agi.llm import (
    build_embedding_provider_or_none,
    build_product_llm,
    llm_identity,
)
from backend.app.agents.product_agi.state import PROGRESS_STEPS
from backend.app.agents.product_agi.tools import iter_agent_tool_names
from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.db.session import get_db, get_session_factory
from backend.app.integrations.mcp.domains import domains_for_agent
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.models.product_agi import ProductAgentRun

log = logging.getLogger(__name__)
router = APIRouter(prefix="/product-agi", tags=["product-agi"])

DEFAULT_OBJECTIVE = (
    "Analyse this workspace's product catalog, demand, inventory and pricing, "
    "then prepare evidence-backed recommendations for human approval."
)


def _worker(run_id: uuid.UUID, merchant_id: uuid.UUID, objective: str) -> None:
    """Run the cycle off the request thread on its own session."""
    db = get_session_factory()()
    try:
        run_row = db.get(ProductAgentRun, run_id)
        if run_row is None or run_row.merchant_id != merchant_id:
            log.error("ProductAgent worker: run %s not found for merchant", run_id)
            return
        agent = ProductAGI(
            db,
            merchant_id,
            llm=build_product_llm(),
            embedding_provider=build_embedding_provider_or_none(),
        )
        agent.run(run_row, objective)
    except Exception:
        log.exception("ProductAgent worker crashed for run %s", run_id)
        try:
            db.rollback()
            run_row = db.get(ProductAgentRun, run_id)
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


def _serialize_run(
    run: ProductAgentRun, db: Session | None = None
) -> dict[str, Any]:
    """Serialize a run with its AUTHORITATIVE status.

    ``product_agent_runs.status`` is a mirror of ``agent_actions.status``.
    Every read surface resolves it through ``effective_run_state`` so the
    run list, the run detail and ``GET /status`` can never report three
    different states for one run — the drift that let the dashboard keep
    claiming "waiting for approval" after every action had been approved.

    ``stored_status`` is kept alongside so a caller can still see the mirror.
    """
    state = run.state or {}
    stored_status = run.status
    if db is not None:
        recs = [
            pa_service.serialize_recommendation(db, run.merchant_id, r)
            for r in pa_service.recommendations_for_run(
                db, run.merchant_id, str(run.id)
            )
        ]
        status, stage, approval_status = pa_service.effective_run_state(run, recs)
    else:
        status, stage, approval_status = (
            run.status,
            run.current_stage,
            run.approval_status,
        )
    return {
        "id": str(run.id),
        "merchant_id": str(run.merchant_id),
        "objective": run.objective,
        "status": status,
        "stored_status": stored_status,
        "stage": stage,
        "approval_status": approval_status,
        "summary": run.summary,
        "metrics": run.metrics or {},
        "analysis_cycle_id": run.analysis_cycle_id,
        "products_analyzed": run.products_analyzed,
        "opportunities_found": run.opportunities_found,
        "recommendations_created": run.recommendations_created,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "started_at": pa_service._iso(run.started_at),  # noqa: SLF001
        "completed_at": pa_service._iso(run.completed_at),  # noqa: SLF001
        "duration_seconds": pa_service.run_duration_seconds(run),
        "state": {
            "stage": state.get("stage"),
            "catalog": state.get("catalog"),
            "performance": state.get("performance"),
            "opportunities": state.get("opportunities"),
            "findings": state.get("findings"),
            "evidence": state.get("evidence"),
            "retrieval_log": state.get("retrieval_log"),
            "knowledge_gaps": state.get("knowledge_gaps"),
            "rag_rounds": state.get("rag_rounds", 0),
            "recommendations": state.get("recommendations"),
            "verification": state.get("verification"),
            "prepared_actions": state.get("prepared_actions"),
            "learning_status": state.get("learning_status"),
            "mcp_calls": state.get("mcp_calls"),
            "tool_call_count": state.get("tool_call_count", 0),
            "llm_calls": state.get("llm_calls", 0),
            "llm_decisions": state.get("llm_decisions"),
            "llm_degraded": state.get("llm_degraded", False),
            "reasoning_status": state.get("reasoning_status"),
            "current_decision": state.get("current_decision"),
            "reasoning_summary": state.get("reasoning_summary"),
            "errors": state.get("errors"),
            "timing": state.get("timing"),
        },
        "result": run.result,
        "errors": run.errors or [],
    }


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------


@router.get("/status")
def status(
    window_days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Complete dashboard read model for the Product Agent workstation.

    ``window_days`` is optional: omitted, it reuses the window the latest
    run actually measured, so the page cannot describe a different period
    than the run it is showing.

    The payload also carries ``analysis_cycle_id`` for the latest run, so
    the page can state truthfully that the displayed state belongs to the
    shared AI Team analysis cycle (see agents/product_agi/cycle.py).
    """
    return pa_service.build_status(db, ctx.merchant_id, window_days=window_days)


@router.get("/catalog")
def catalog(
    window_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Real catalog rows plus the four preview segments, all derived."""
    return pa_service.catalog_view(db, ctx.merchant_id, window_days=window_days)


@router.get("/platforms")
def platforms(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Honest platform connection states (never assumed)."""
    return {"platforms": pa_service.platform_states(db, ctx.merchant_id)}


@router.get("/tools")
def tools(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """What this agent may discover, and the MCP domains it was granted."""
    client_domains = list(domains_for_agent("product_agent"))
    registry = get_mcp_registry()
    granted = [
        entry
        for entry in registry.catalog_for_agent("product_agent", include_write=False)
    ]
    return {
        "agent": "product_agent",
        "domains": client_domains,
        "workflow_steps": [
            {"top": top, "bottom": bottom} for top, bottom in PROGRESS_STEPS
        ],
        "expected_tools": sorted(iter_agent_tool_names()),
        "tools": granted,
        "mcp_tool_count": len(registry.names()),
    }


@router.get("/runs")
def runs(
    limit: int = Query(default=20, ge=1, le=100),
    analysis_cycle_id: str | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Run history, tenant-scoped. Read-only: listing never creates a run.

    ``analysis_cycle_id`` mirrors the Marketing Agent's run listing: it
    narrows the list to one shared AI Team analysis cycle, still scoped to
    the authenticated merchant, so another tenant's cycle id returns an
    empty list rather than another tenant's runs.
    """
    return {
        "runs": [
            _serialize_run(r, db)
            for r in pa_service.list_runs(
                db,
                ctx.merchant_id,
                limit=limit,
                analysis_cycle_id=analysis_cycle_id,
            )
        ]
    }


@router.post("/runs", status_code=202)
def start_run(
    background_tasks: BackgroundTasks,
    window_days: int = Query(default=90, ge=1, le=365),
    objective: str = Query(default=DEFAULT_OBJECTIVE, min_length=8, max_length=1000),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Start a Product Agent run (operator+).

    The nine-stage cycle runs in the BACKGROUND and the request returns a
    ``run_id`` immediately, so the browser never waits through an
    LLM/RAG/MCP cycle. The frontend polls the run's state.

    Idempotency: this endpoint is no longer the Product Agent dashboard's
    trigger — Start Analysis on the AI Team page owns that. When a Product
    Agent run is already in flight for this tenant (for example one
    dispatched by an active shared analysis cycle), this endpoint JOINS
    that run and reports ``already_running`` instead of creating a second
    one, so an accidental trigger can never produce a duplicate run.
    """
    existing = pa_service.active_run(db, ctx.merchant_id)
    if existing is not None:
        return {
            "run_id": str(existing.id),
            "status": existing.status,
            "stage": existing.current_stage,
            "objective": existing.objective,
            "already_running": True,
            "analysis_cycle_id": existing.analysis_cycle_id,
            "llm_configured": bool(
                (existing.metrics or {}).get("llm_configured")
            ),
            "llm_provider": existing.llm_provider,
            "llm_model": existing.llm_model,
        }
    configured, provider, model = llm_identity()
    run_row = ProductAgentRun(
        merchant_id=ctx.merchant_id,
        objective=objective,
        status="queued",
        current_stage="understand_catalog",
        llm_provider=provider,
        llm_model=model,
        metrics={
            "window_days": window_days,
            "product_count": None,
            "opportunity_count": None,
            "finding_count": 0,
            "recommendation_count": 0,
            "action_count": 0,
            "executed_count": 0,
            "llm_configured": configured,
        },
    )
    db.add(run_row)
    db.commit()
    background_tasks.add_task(_worker, run_row.id, ctx.merchant_id, objective)
    return {
        "run_id": str(run_row.id),
        "status": run_row.status,
        "stage": run_row.current_stage,
        "objective": run_row.objective,
        "already_running": False,
        "analysis_cycle_id": run_row.analysis_cycle_id,
        "llm_configured": configured,
        "llm_provider": provider,
        "llm_model": model,
    }


@router.get("/runs/{run_id}")
def run_detail(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    run = pa_service.get_run(db, ctx.merchant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return _serialize_run(run, db)


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Request cancellation of an in-flight run.

    The run is marked ``cancelled`` immediately so no surface can keep
    reporting a superseded run as active, and the loop also checks the
    cooperative flag between stages.
    """
    run = pa_service.get_run(db, ctx.merchant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    if run.status in {"queued", "running"}:
        state = dict(run.state or {})
        state["cancelled"] = True
        run.state = state
        run.status = "cancelled"
        db.commit()
    return _serialize_run(run, db)


@router.get("/runs/{run_id}/findings")
def run_findings(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    run = pa_service.get_run(db, ctx.merchant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    rows = pa_service.findings_for_run(db, ctx.merchant_id, run_id)
    return {
        "run_id": str(run.id),
        "findings": [pa_service.serialize_finding(r) for r in rows],
    }


@router.get("/runs/{run_id}/recommendations")
def run_recommendations(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    run = pa_service.get_run(db, ctx.merchant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    rows = pa_service.recommendations_for_run(db, ctx.merchant_id, run_id)
    return {
        "run_id": str(run.id),
        "recommendations": [
            pa_service.serialize_recommendation(db, ctx.merchant_id, r) for r in rows
        ],
    }


@router.get("/runs/{run_id}/activity")
def run_activity(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    run = pa_service.get_run(db, ctx.merchant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    rows = list_events(
        db, run.id, ctx.merchant_id, after_seq=after_seq, limit=limit
    )
    serialized = _serialize_run(run, db)
    return {
        "run_id": str(run.id),
        "status": serialized["status"],
        "stage": serialized["stage"],
        "events": [serialize_event(e) for e in rows],
    }


__all__ = ["router"]