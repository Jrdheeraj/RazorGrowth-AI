"""Agent observability + orchestration APIs — Phase 5 Feature 21.

Endpoints (final paths after the single /api application prefix):
  GET  /api/agents                 — analyst+ (registry + observability)
  GET  /api/agents/runs            — analyst+, tenant-scoped
  GET  /api/agents/runs/{run_id}   — analyst+, tenant-scoped
  POST /api/agents/run             — operator+ (proposals only)

The POST endpoint drives GrowthAgentOrchestrator. It can only CREATE
proposals — approval and execution remain Phase 4 human-only operations
restricted to owner/admin roles. Agents are not users: no token, role,
or membership path exists for them.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    MerchantContext,
    merchant_ctx,
    operator_ctx,
    resolve_claimed_merchant,
)
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


@router.get("/agents", response_model=AgentsListResponse)
def list_agents(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Agent registry with capability transparency (Feature 13/15).

    The static agent catalog is product-level information; the
    observability summary is merchant-scoped to the authenticated caller.
    """
    runs = AgentRunService(db)
    return {
        "agents": agent_catalog(),
        "observability": runs.observability_summary(ctx.merchant_id),
    }


@router.get("/agents/runs", response_model=AgentRunsResponse)
def list_agent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    orchestrator_run_id: str | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List agent runs for the caller's merchant (tenant-isolated)."""
    runs = AgentRunService(db).list_runs(
        ctx.merchant_id,
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
            "orchestrator_run_id": run.orchestrator_run_id,
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
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Retrieve one agent run; other tenants' runs are indistinguishable
    from nonexistent ones (404 — no existence leak)."""
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    run = AgentRunService(db).get_run(rid, merchant_id=ctx.merchant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return {
        "id": str(run.id),
        "merchant_id": str(run.merchant_id) if run.merchant_id else None,
        "agent_name": run.agent_name,
        "status": str(getattr(run.status, "value", run.status)),
        "mode": run.mode,
        "orchestrator_run_id": run.orchestrator_run_id,
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


@router.get("/agents/active-run")
def get_active_run(
    stale_after_seconds: int = Query(default=900, ge=5, le=86400),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Authoritative, READ-ONLY answer to "is an analysis really running?".

    This is what the dashboard's mount and poll paths call. It exists because
    the previous behaviour inferred liveness from the mere PRESENCE of a
    ``running`` row, which a crashed worker leaves behind -- so a dead run was
    reported as active forever and the page showed "ANALYZING..." indefinitely.

    Three guarantees:

    * **Read-only.** It never creates, mutates or cancels anything. Opening the
      page, refreshing, remounting under StrictMode and polling all call this and
      all are safe, which is precisely why the staleness bound can live here
      instead of being faked in the client.
    * **Liveness-bounded.** A row counts as active only while its heartbeat (or,
      for pre-tracking rows, its last update) is inside the staleness window.
    * **Tenant-scoped.** Another tenant's cycle is indistinguishable from none.

    Returns ``{"active": false, "idle_reason": ...}`` when nothing is running,
    which is the correct answer for a freshly opened dashboard.
    """
    from backend.app.services.workflow_run_service import active_run_report

    return active_run_report(
        db, merchant_id=ctx.merchant_id, stale_after_seconds=stale_after_seconds
    ).to_dict()


@router.post("/agents/runs/{run_id}/cancel")
def cancel_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Request cancellation of a specific analysis cycle.

    Stops the orchestrator starting any further step, terminalises the cycle as
    ``cancelled`` immediately, and closes out the step that was in flight.

    Scope is exactly one run: the run id in the path, resolved within the
    caller's merchant. A cycle belonging to another tenant is a 404, not a 403,
    so this endpoint leaks no existence information.

    A cycle that has already finished is returned unchanged. Terminal really
    means terminal -- a late cancellation cannot rewrite a completed outcome.
    """
    from backend.app.services.workflow_run_service import (
        StaleLeaseError,
        WorkflowNotFound,
        request_cancel,
    )

    try:
        row = request_cancel(db, merchant_id=ctx.merchant_id, run_id=run_id)
    except WorkflowNotFound:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    except StaleLeaseError as exc:
        # The cycle moved under us (a takeover). Report honestly rather than
        # pretending the cancellation landed.
        raise HTTPException(status_code=409, detail="RUN_SUPERSEDED")
    return {
        "orchestrator_run_id": row.run_id,
        "status": str(getattr(row.status, "value", row.status)),
        "cancel_requested_at": (
            row.cancel_requested_at.isoformat() if row.cancel_requested_at else None
        ),
        "cancelled": str(getattr(row.status, "value", row.status)) == "cancelled",
    }


@router.post("/agents/run", response_model=OrchestratorRunResponse)
def run_agents(
    request: AgentRunRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Trigger a controlled orchestration run (operator role or above).

    Produces opportunities/signals/proposals only. Nothing executes and
    nothing is approved without a human owner/admin (Phase 4 invariants).

    In mode="team" (the AI Team "Start Analysis" entry point) execution is
    REQUEST-INDEPENDENT: the cycle and audit rows are persisted, the
    Marketing Agent, the Product Agent and the orchestrator plan are
    dispatched to server-owned background workers, and this endpoint
    returns 202 with the cycle id immediately. The browser only observes
    via polling; navigation, refresh, or disconnect never cancels backend
    execution. Both autonomous employees share the same cycle id and run
    concurrently — neither waits for the other. Other modes run
    synchronously (unchanged legacy behavior).
    """
    if request.mode not in ("fast", "deep", "growth_team", "team"):
        raise HTTPException(status_code=422, detail="mode must be 'fast', 'deep', 'growth_team', or 'team'")
    merchant_id = resolve_claimed_merchant(ctx, request.merchant_id)

    settings = get_settings()
    llm = None
    # One shared resolver decides which provider is in use, so this route and
    # the other LLM call sites can never disagree about it. Previously each
    # re-implemented the choice.
    from backend.app.ai.llm.provider import resolve_llm_provider

    resolved = resolve_llm_provider(settings)
    api_key = resolved.api_key if resolved else ""
    llm_provider = resolved.name if resolved else settings.LLM_PROVIDER
    llm_model = resolved.model if resolved else settings.LLM_MODEL
    if request.mode in ("deep", "growth_team") and api_key:
        # Synchronous legacy modes build the LLM inline (unchanged).
        llm = resolved.build(
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
        "objective": request.objective,
    }
    # Merge any additional params from the request body
    if request.params:
        params.update(request.params)

    # Shared analysis cycle for AI Team runs. Generated here (not inside
    # the orchestrator) so the Marketing Agent worker can be stamped with
    # the identical cycle id BEFORE the sequential plan starts.
    cycle_id: str | None = None
    if request.mode == "team":
        # ── duplicate-start guard (server side) ──────────────────────────
        # The browser guards double-clicks with React state, which is advisory:
        # two tabs, a retry, or a refresh mid-request all bypass it. Here the
        # database is the authority. If this merchant already has a live cycle,
        # that cycle is RETURNED rather than a second one created -- an explicit
        # Start therefore yields exactly one run, and a repeated Start is
        # idempotent instead of doubling the work.
        #
        # Deliberately keyed on the merchant's own cycles only, so independent
        # merchants are entirely unaffected.
        from backend.app.services.workflow_run_service import active_run_report

        existing = active_run_report(db, merchant_id=merchant_id)
        if existing.active and existing.run_id:
            log.info(
                "Start Analysis for merchant %s joined existing live cycle %s "
                "instead of creating a duplicate",
                merchant_id, existing.run_id,
            )
            response.status_code = 202
            return {
                "orchestrator_run_id": existing.run_id,
                "merchant_id": str(merchant_id),
                "mode": request.mode,
                "status": "running",
                "totals": {
                    "opportunities_created": 0,
                    "actions_proposed": 0,
                    "signals_detected": 0,
                    "insights_generated": 0,
                    "experiments_proposed": 0,
                    "failed_agents": 0,
                    "reused_steps": 0,
                },
                "agents": [],
                "ranked_opportunities": [],
                "resumed": True,
                "deduplicated": True,
            }

        cycle_id = uuid.uuid4().hex
        from backend.app.services.workflow_run_service import (
            EXECUTION_ENGINE_LANGGRAPH,
            WorkflowRunService,
        )
        from backend.app.agents.orchestrator import AI_TEAM_PLAN

        wf = WorkflowRunService(db)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant_id,
            run_id=cycle_id,
            mode="team",
            plan=AI_TEAM_PLAN,
            # The background worker below runs orchestrator.run(), whose
            # default engine is LangGraph. Record that provenance at creation
            # so recovery routes the cycle back to the same executor.
            execution_engine=EXECUTION_ENGINE_LANGGRAPH,
        )
        db.commit()

        try:
            _start_team_marketing_agent(db, merchant_id, params, cycle_id, workflow_id=workflow_row.id)
        except Exception:
            # Isolation boundary (defense in depth — the helper already
            # contains its own failures): Start Analysis never fails
            # because the Marketing Agent could not start.
            log.exception("AI Team Marketing Agent startup failed (isolated)")
            try:
                db.rollback()
            except Exception:
                pass
        # Same shared cycle, same user action, independent worker. Added
        # alongside the Marketing Agent above, never in front of it: both
        # are dispatched and neither waits for the other.
        try:
            _start_team_product_agent(db, merchant_id, params, cycle_id, workflow_id=workflow_row.id)
        except Exception:
            log.exception("AI Team Product Agent startup failed (isolated)")
            try:
                db.rollback()
            except Exception:
                pass
        # Request-independent execution: persist nothing more here; the
        # server-owned worker below owns the plan lifecycle on its own
        # session. Return 202 immediately — the frontend polls by cycle.
        # The worker rebuilds its own LLM from server-side settings, so no
        # request resource (session, client, connection) leaks into it.
        llm_cfg: dict[str, Any] = {}
        if api_key:
            llm_cfg = {
                "provider": llm_provider,
                "model": llm_model,
                "timeout": settings.LLM_REQUEST_TIMEOUT,
                "max_retries": settings.LLM_MAX_RETRIES,
                "max_tokens": settings.LLM_MAX_TOKENS,
            }
        try:
            from backend.app.db.session import get_session_factory

            background_tasks.add_task(
                _run_team_orchestrator_worker,
                get_session_factory(),
                merchant_id,
                params,
                cycle_id,
                llm_cfg,
            )
        except Exception:
            log.exception("Failed to dispatch team orchestrator worker")
            raise HTTPException(status_code=500, detail="AGENT_RUN_FAILED")
        response.status_code = 202
        return {
            "orchestrator_run_id": cycle_id,
            "merchant_id": str(merchant_id),
            "mode": "team",
            "status": "running",
            "totals": {
                "opportunities_created": 0,
                "actions_proposed": 0,
                "signals_detected": 0,
                "insights_generated": 0,
                "experiments_proposed": 0,
                "failed_agents": 0,
            },
            "agents": [],
            "ranked_opportunities": [],
        }

    try:
        summary = orchestrator.run(
            merchant_id, mode=request.mode, params=params, run_id=cycle_id
        )
    except MerchantNotFoundError:
        # Body-supplied ids are validated here (Phase 4/5 contract preserved):
        # unknown merchant → 404, indistinguishable across tenants.
        db.rollback()
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    except Exception as exc:  # central safety net; log details server-side only
        log.exception("Orchestration failed")
        db.rollback()
        raise HTTPException(status_code=500, detail="AGENT_RUN_FAILED")

    try:
        db.commit()
    except Exception as exc:
        log.warning("Failed to commit orchestration results: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="AGENT_RUN_COMMIT_FAILED")

    return summary.to_dict()


def _run_team_orchestrator_worker(
    session_factory: Any,
    merchant_id: uuid.UUID,
    params: dict[str, Any],
    cycle_id: str,
    llm_cfg: dict[str, Any],
) -> None:
    """Server-owned AI Team plan execution. Never raises.

    Runs on a fresh DB session after the HTTP response has been sent, so
    browser navigation, refresh, or disconnect cannot cancel it. Agent
    audit rows are committed per step (see orchestrator team branch), and
    a crash best-effort marks still-running rows FAILED instead of
    leaving them stuck.
    """
    db: Session | None = None
    try:
        db = session_factory()
        from backend.app.agents.orchestrator import (
            GrowthAgentOrchestrator as _GAO,
        )

        llm = None
        if llm_cfg.get("provider"):
            try:
                from backend.app.core.config import get_settings
                from backend.app.ai.llm.provider import resolve_llm_provider

                settings = get_settings()
                # The Cloudflare credential stays server-side; only primitive
                # config crosses into the worker. Re-resolve the credential here
                # and build from the SHARED resolver so the background worker
                # uses exactly the same provider as the request that spawned it.
                resolved = resolve_llm_provider(settings)
                if resolved is not None:
                    llm = resolved.build(
                        timeout=int(llm_cfg.get("timeout", settings.LLM_REQUEST_TIMEOUT)),
                        max_retries=int(llm_cfg.get("max_retries", settings.LLM_MAX_RETRIES)),
                        max_tokens=int(llm_cfg.get("max_tokens", settings.LLM_MAX_TOKENS)),
                    )
            except Exception:
                log.exception("Team worker: LLM setup failed; continuing without LLM")
                llm = None
        orchestrator = _GAO(db, llm=llm, embedding_provider=None)
        orchestrator.run(merchant_id, mode="team", params=params, run_id=cycle_id)
        try:
            db.commit()
        except Exception:
            log.exception("Team worker: final commit failed")
            db.rollback()
    except Exception:
        log.exception("Team orchestrator worker crashed for cycle %s", cycle_id)
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                from datetime import datetime, timezone

                from sqlalchemy import select as _select

                from backend.app.agents.marketing_agi.cycle import (
                    MARKETING_AGI_AGENT_NAME,
                )
                from backend.app.agents.product_agi.cycle import (
                    PRODUCT_AGENT_AGENT_NAME,
                )
                from backend.app.models.agent_run import AgentRun
                from backend.app.models.agent_workflow import AgentWorkflowRun
                from backend.app.models.enums import AgentRunStatus, WorkflowStatus

                # Fail only orchestrator-owned agent runs that were mid-flight.
                # MarketingAGI and ProductAGI are independent parallel workers
                # with their own isolated error handlers.
                stuck = list(
                    db.scalars(
                        _select(AgentRun).where(
                            AgentRun.merchant_id == merchant_id,
                            AgentRun.orchestrator_run_id == cycle_id,
                            AgentRun.status == AgentRunStatus.running,
                            AgentRun.agent_name.notin_([MARKETING_AGI_AGENT_NAME, PRODUCT_AGENT_AGENT_NAME]),
                        )
                    ).all()
                )
                for row in stuck:
                    row.status = AgentRunStatus.failed
                    row.completed_at = datetime.now(timezone.utc)
                    row.errors = list(row.errors or []) + ["worker_crashed"]

                wf_row = db.scalar(
                    _select(AgentWorkflowRun).where(
                        AgentWorkflowRun.merchant_id == merchant_id,
                        AgentWorkflowRun.run_id == cycle_id,
                    )
                )
                if wf_row and wf_row.status == WorkflowStatus.running.value:
                    wf_row.status = WorkflowStatus.failed.value
                    wf_row.completed_at = datetime.now(timezone.utc)
                    wf_row.errors = list(wf_row.errors or []) + ["worker_crashed"]
                db.commit()
            except Exception:
                log.error("Team worker: could not persist failure state for %s", cycle_id)
                try:
                    db.rollback()
                except Exception:
                    pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _start_team_marketing_agent(
    db: Session,
    merchant_id: uuid.UUID,
    params: dict[str, Any],
    cycle_id: str,
    workflow_id: uuid.UUID | None = None,
) -> None:
    """Start the Marketing Agent as part of an AI Team analysis cycle.

    Creates the cycle-linked MarketingAGI run row plus its AgentRun audit
    row (visible on the AI Team page as RUNNING), then dispatches the
    bounded loop to a background worker. Every failure path is swallowed:
    the Marketing Agent must never break the team analysis.
    """
    try:
        from backend.app.agents.marketing_agi.cycle import (
            MARKETING_AGI_AGENT_NAME,
            create_cycle_run,
            trigger_marketing_agi_parallel,
        )
        from backend.app.services.agent_run_service import AgentRunService

        objective = str(params.get("objective") or "AI Team analysis")
        run_row = create_cycle_run(
            db,
            merchant_id=merchant_id,
            objective=objective,
            cycle_id=cycle_id,
        )
        db.flush()
        # Audit row so the AI Team page lists Marketing Agent under this cycle.
        AgentRunService(db).start_run(
            merchant_id=merchant_id,
            agent_name=MARKETING_AGI_AGENT_NAME,
            orchestrator_run_id=cycle_id,
            mode="team",
            input_summary={"objective": objective[:200]},
            workflow_id=workflow_id,
        )
        db.flush()
        from backend.app.db.session import get_session_factory

        # Commit the rows BEFORE the worker thread can see them: the
        # worker uses its own session and must observe committed state.
        try:
            db.commit()
        except Exception:
            log.exception("Failed to commit team Marketing Agent rows")
            db.rollback()
            return
        trigger_marketing_agi_parallel(
            get_session_factory(),
            merchant_id=merchant_id,
            objective=objective,
            cycle_id=cycle_id,
            run_id=run_row.id,
        )
    except Exception:
        # Isolation boundary: Marketing Agent startup must never fail Start Analysis.
        log.exception("AI Team Marketing Agent startup failed (isolated)")
        try:
            db.rollback()
        except Exception:
            pass


def _start_team_product_agent(
    db: Session,
    merchant_id: uuid.UUID,
    params: dict[str, Any],
    cycle_id: str,
    workflow_id: uuid.UUID | None = None,
) -> None:
    """Start the Product Agent as part of an AI Team analysis cycle.

    Structurally identical to ``_start_team_marketing_agent`` and
    deliberately kept as its own helper: it reuses the existing
    ``ProductAgentRun`` row, the existing ProductAGI loop (shared MCP
    client, RAG, safety gate, approval wiring) and the existing AgentRun
    audit table. It creates NO new orchestrator, NO new MCP client and NO
    new approval system. Every failure path is swallowed so the Product
    Agent can never break the team analysis.
    """
    try:
        from backend.app.agents.product_agi.cycle import (
            PRODUCT_AGENT_AGENT_NAME,
            create_cycle_run as create_product_cycle_run,
            trigger_product_agent_parallel,
        )
        from backend.app.services.agent_run_service import AgentRunService

        objective = str(params.get("objective") or "AI Team analysis")
        run_row = create_product_cycle_run(
            db,
            merchant_id=merchant_id,
            objective=objective,
            cycle_id=cycle_id,
            window_days=params.get("window_days", 90),
        )
        db.flush()
        # Audit row so the AI Team page lists Product Agent under this cycle.
        AgentRunService(db).start_run(
            merchant_id=merchant_id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            orchestrator_run_id=cycle_id,
            mode="team",
            input_summary={"objective": objective[:200]},
            workflow_id=workflow_id,
        )
        db.flush()
        from backend.app.db.session import get_session_factory

        # Commit the rows BEFORE the worker thread can see them: the
        # worker uses its own session and must observe committed state.
        try:
            db.commit()
        except Exception:
            log.exception("Failed to commit team Product Agent rows")
            db.rollback()
            return
        trigger_product_agent_parallel(
            get_session_factory(),
            merchant_id=merchant_id,
            objective=objective,
            cycle_id=cycle_id,
            run_id=run_row.id,
        )
    except Exception:
        # Isolation boundary: Product Agent startup must never fail Start Analysis.
        log.exception("AI Team Product Agent startup failed (isolated)")
        try:
            db.rollback()
        except Exception:
            pass
