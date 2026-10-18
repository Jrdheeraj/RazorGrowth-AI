"""
Manager Agent coordination APIs.

Final paths after the single ``/api`` application prefix:

  GET  /api/manager/roster                  live registry (count is never hardcoded)
  POST /api/manager/plan                     validated plan — planning only, runs nothing
  GET  /api/manager/workflows/{workflow_id}  real workflow state from audit rows
  GET  /api/manager/metrics                  real dashboard figures
  GET  /api/manager/actions                  pending proposals awaiting a human

Why a separate router instead of more handlers in ``agents.py``:

* ``/api/agents/run`` is the orchestrator's execution entry point. Planning is
  a genuinely different operation — it must be able to return a plan WITHOUT
  running an agent — so it gets its own endpoint rather than a flag on the
  execution route.
* Every handler here is merchant-scoped through the existing dependencies and
  every read is filtered by ``ctx.merchant_id``, so a workflow, action or run
  belonging to another workspace is indistinguishable from one that does not
  exist.

Nothing in this router approves, executes or bypasses a guardrail. Actions
proposed by specialists stay in the Phase 4 approval workflow and are moved
only by the existing authorized endpoints.
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
from backend.app.schemas.phase5 import (
    ManagerActionsResponse,
    ManagerMetricsResponse,
    ManagerPlanRequest,
    ManagerPlanResponse,
    ManagerRosterResponse,
    ManagerWorkflowReportResponse,
)
from backend.app.services.manager_plan_service import (
    ManagerCoordinationService,
    ManagerWorkflowNotFound,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["manager"])


def _service(db: Session) -> ManagerCoordinationService:
    """
    Build the coordination service with the SAME shared LLM resolver every
    other route uses, so the Manager can never disagree with the orchestrator
    about which provider is configured.
    """
    settings = get_settings()
    llm = None
    try:
        from backend.app.ai.llm.provider import resolve_llm_provider

        resolved = resolve_llm_provider(settings)
        if resolved is not None and resolved.api_key:
            llm = resolved.build(
                timeout=settings.LLM_REQUEST_TIMEOUT,
                max_retries=settings.LLM_MAX_RETRIES,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
    except Exception:  # noqa: BLE001 - planning must degrade without a provider
        log.exception("LLM provider unavailable for the Manager Agent")
        llm = None
    return ManagerCoordinationService(db, llm=llm)


@router.get("/manager/roster", response_model=ManagerRosterResponse)
def manager_roster(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    The live agent registry.

    Every unique registered agent with its genuinely registered tools.
    Declared tool names with no implementation are reported under
    ``unimplemented_tools`` rather than presented as capabilities.
    """
    return _service(db).roster()


@router.post("/manager/plan", response_model=ManagerPlanResponse)
def create_manager_plan(
    request: ManagerPlanRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Turn a merchant goal into a validated execution plan. Executes nothing.

    The returned ``workflow_id`` is the correlation id to pass to
    ``POST /api/agents/run`` when the merchant chooses to execute, so the
    cycle's audit rows correlate with the plan that produced them.

    ``proposed_tasks`` is treated as untrusted input: unknown agent ids,
    duplicate task ids, invalid dependency references, circular dependencies,
    tools an agent does not own and model-issued permissions are all rejected
    and reported under ``validation.rejections``.
    """
    merchant_id = resolve_claimed_merchant(ctx, request.merchant_id)
    plan = _service(db).build_plan(
        merchant_id=merchant_id,
        objective=request.objective,
        window_days=request.window_days,
        constraints=list(request.constraints or ()),
        budget=request.budget,
        deadline=request.deadline,
        proposed_tasks=list(request.proposed_tasks) if request.proposed_tasks else None,
    )
    # An invalid plan is returned, not executed: the merchant sees exactly
    # which parts were rejected and why.
    return plan


@router.get("/manager/workflows/{workflow_id}", response_model=ManagerWorkflowReportResponse)
def manager_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Real state of one workflow, rebuilt from the caller's ``AgentRun`` rows.

    Reports the intended plan next to what actually ran, classifies each
    agent's real status, and states plainly that these rows are progress
    records rather than a resumable checkpoint.
    """
    try:
        return _service(db).get_workflow(merchant_id=ctx.merchant_id, workflow_id=workflow_id)
    except ManagerWorkflowNotFound:
        # Same response as a workflow owned by another merchant: no existence
        # leak across tenants.
        raise HTTPException(status_code=404, detail="WORKFLOW_NOT_FOUND")


@router.get("/manager/metrics", response_model=ManagerMetricsResponse)
def manager_metrics(
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Dashboard figures computed from real rows.

    No percentage change, trend or duration is invented here; each value is
    either counted from stored data or reported as unavailable with a reason.
    """
    return _service(db).metrics(merchant_id=ctx.merchant_id, window_days=window_days)


@router.get("/manager/actions", response_model=ManagerActionsResponse)
def manager_actions(
    limit: int = Query(default=50, ge=1, le=200),
    workflow_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Pending action proposals with their real originating agent and workflow.

    Read-only. Reviewing, approving and rejecting stay in the existing
    authorized endpoints; this view never transitions an action's state.
    """
    return _service(db).pending_actions(
        merchant_id=ctx.merchant_id, limit=limit, workflow_id=workflow_id
    )
