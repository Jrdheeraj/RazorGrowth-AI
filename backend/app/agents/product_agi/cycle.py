"""AI Team shared-cycle integration for the Product Agent.

This module is the ONLY bridge between the AI Team orchestrator
(POST /api/agents/run, mode="team") and the autonomous ProductAGI
loop. It is a deliberate mirror of ``agents/marketing_agi/cycle.py`` so
both specialists join the SAME shared analysis cycle using the SAME
conventions. It provides:

  create_cycle_run(db, merchant_id, objective, cycle_id, window_days)
      Idempotently create the ProductAgentRun belonging to ``cycle_id``
      (the orchestrator_run_id shared with sibling agents). Calling it
      twice with the same cycle returns the existing row — exactly one
      Product Agent execution per analysis cycle. The LLM identity
      (shared backend-only provider) is stamped on the row.

  run_cycle_worker(session_factory, run_id, merchant_id, objective,
                   cycle_id)
      Execute the bounded ProductAGI loop on a worker session and close
      out the AgentRun audit row. Never raises: LLM/loop failures mark
      the run failed/degraded without touching sibling agents.

  trigger_product_agent_parallel(..., dispatch=...)
      Start the worker without waiting for it (default: daemon thread),
      so the Product Agent runs in parallel with the Marketing Agent and
      the sequential AI Team plan and never blocks them. ``dispatch`` is
      injectable for tests.

Nothing here rebuilds the Product Agent: the loop, the shared MCP
client, the RAG, the safety gate and the approval wiring all stay in
``agents/product_agi`` and ``integrations/mcp``. This module only owns
run creation, worker dispatch and audit-row bookkeeping.

Tenant isolation: the merchant id always comes from the backend
authenticated context; it is never model-supplied, and the worker
session is bound to the given merchant id only.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

#: Audit-row name. Matches ProductAGI.NAME so the AI Team page can key
#: the same slot the agent already owns.
PRODUCT_AGENT_AGENT_NAME = "ProductAGI"

#: Terminal Product Agent run statuses. Anything outside this set means
#: the loop never reached a legitimate end state and must not be
#: reported as a successful audit row.
TERMINAL_RUN_STATUSES = frozenset(
    {
        "waiting_approval",
        "approved_awaiting_execution",
        "executing",
        "completed_no_actions",
        "completed",
        "completed_with_failures",
        "blocked",
        "failed",
        "cancelled",
    }
)

#: ProductAGI run statuses that represent a genuinely finished analysis.
#: ``failed``/``blocked`` are terminal but NOT successful — the AI Team
#: page must show them as errors, never as a completed run.
SUCCESSFUL_RUN_STATUSES = frozenset(
    {
        "waiting_approval",
        "completed_no_actions",
        "completed",
        "completed_with_failures",
    }
)


def run_status_value(status: Any) -> str:
    """The plain string form of a Product Agent run status.

    ``ProductAGI._sync_row`` assigns the ``RunStatus`` enum member to the
    mapped column, so an in-Python row can hold either a ``str`` or the
    enum. Reading it through this helper keeps the audit-row mapping
    honest instead of comparing ``"RunStatus.completed_no_actions"``.
    """
    return str(getattr(status, "value", status))


def create_cycle_run(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
    window_days: int = 90,
) -> Any:
    """Create (or return the existing) ProductAgentRun for a cycle.

    Idempotency: at most one run per (merchant, cycle). Re-entrant calls
    — retries, double-clicks, re-dispatch — return the existing row, so a
    shared analysis cycle can never fan out into two Product Agent runs.
    """
    from backend.app.models.product_agi import ProductAgentRun

    existing = db.scalar(
        select(ProductAgentRun).where(
            ProductAgentRun.merchant_id == merchant_id,
            ProductAgentRun.analysis_cycle_id == cycle_id,
        )
    )
    if existing is not None:
        return existing

    from backend.app.agents.product_agi.llm import llm_identity

    configured, provider, model = llm_identity()
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        days = 90
    if not 1 <= days <= 365:
        days = 90
    run_row = ProductAgentRun(
        merchant_id=merchant_id,
        objective=objective,
        status="queued",
        current_stage="understand_catalog",
        analysis_cycle_id=cycle_id,
        llm_provider=provider,
        llm_model=model,
        metrics={
            "window_days": days,
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
    db.flush()
    return run_row


def _complete_audit_row(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    cycle_id: str,
    status: str,
    output: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> None:
    """Close the AgentRun audit row so the AI Team page shows live status.

    Mirrors marketing_agi.cycle._complete_audit_row: only the ProductAGI
    row for this (merchant, cycle) is touched, and an unknown status
    fails closed to ``failed``.
    """
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.enums import AgentRunStatus

    row = db.scalar(
        select(AgentRun).where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.orchestrator_run_id == cycle_id,
            AgentRun.agent_name == PRODUCT_AGENT_AGENT_NAME,
        )
    )
    if row is None:
        return
    try:
        row.status = AgentRunStatus(status)
    except ValueError:
        row.status = AgentRunStatus.failed
    row.completed_at = datetime.now(timezone.utc)
    if output is not None:
        row.output_summary = output
    row.errors = list(errors) if errors is not None else []
    db.flush()


def run_cycle_worker(
    session_factory: Any,
    run_id: uuid.UUID,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
) -> None:
    """Execute the Product Agent loop for a cycle. Never raises."""
    db: Session = session_factory()
    try:
        from backend.app.agents.product_agi.agent import ProductAGI
        from backend.app.agents.product_agi.llm import (
            build_embedding_provider_or_none,
            build_product_llm,
        )
        from backend.app.models.product_agi import ProductAgentRun

        run_row = db.get(ProductAgentRun, run_id)
        if run_row is None or run_row.merchant_id != merchant_id:
            log.error(
                "ProductAGI cycle worker: run %s not found for merchant", run_id
            )
            return
        try:
            llm = build_product_llm()
        except Exception:
            log.exception("ProductAGI cycle worker: LLM setup failed")
            llm = None
        try:
            embedder = build_embedding_provider_or_none()
        except Exception:
            log.warning("ProductAGI cycle worker: embedder unavailable")
            embedder = None
        agent = ProductAGI(db, merchant_id, llm=llm, embedding_provider=embedder)
        agent.run(run_row, objective, analysis_cycle_id=cycle_id)
        state = run_row.state or {}
        metrics = run_row.metrics or {}
        output = {
            "status": run_row.status,
            "stage": run_row.current_stage,
            "approval_status": run_row.approval_status,
            "products_analyzed": run_row.products_analyzed,
            "opportunities_found": run_row.opportunities_found,
            "recommendations_created": run_row.recommendations_created,
            "finding_count": metrics.get("finding_count", len(state.get("findings", []))),
            "action_count": metrics.get("action_count", 0),
            "executed_count": metrics.get("executed_count", 0),
            "tool_calls": state.get("tool_call_count", 0),
            "verification": state.get("verification"),
            "prepared_actions": state.get("prepared_actions"),
        }
        # Terminal AND successful → completed. Terminal but failed/blocked →
        # failed. Anything else never reached a legitimate end state.
        audit_status = (
            "completed"
            if run_status_value(run_row.status) in SUCCESSFUL_RUN_STATUSES
            else "failed"
        )
        errors = list(run_row.errors or []) or None
        _complete_audit_row(
            db,
            merchant_id=merchant_id,
            cycle_id=cycle_id,
            status=audit_status,
            output=output,
            errors=errors,
        )
        db.commit()
    except Exception:
        log.exception("ProductAGI cycle worker crashed for run %s", run_id)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            from backend.app.models.product_agi import ProductAgentRun

            run_row = db.get(ProductAgentRun, run_id)
            if run_row is not None and run_status_value(run_row.status) in {
                "queued",
                "running",
            }:
                run_row.status = "failed"
                run_row.completed_at = datetime.now(timezone.utc)
                run_row.errors = ["worker_crashed"]
            _complete_audit_row(
                db,
                merchant_id=merchant_id,
                cycle_id=cycle_id,
                status="failed",
                errors=["worker_crashed"],
            )
            db.commit()
        except Exception:
            log.error("Could not persist failure state for run %s", run_id)
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def trigger_product_agent_parallel(
    session_factory: Any,
    *,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
    run_id: uuid.UUID,
    dispatch: Callable[[Callable[[], None]], None] | None = None,
) -> None:
    """Start the cycle worker without blocking the caller.

    The Product Agent executes independently and in parallel with the
    Marketing Agent and the sibling AI Team plan agents. Dispatch failures
    are swallowed: the AI Team analysis must never fail because the
    Product Agent could not start.
    """

    def _work() -> None:
        run_cycle_worker(session_factory, run_id, merchant_id, objective, cycle_id)

    try:
        if dispatch is not None:
            dispatch(_work)
        else:
            thread = threading.Thread(
                target=_work,
                name=f"product-agi-cycle-{cycle_id[:8]}",
                daemon=True,
            )
            thread.start()
    except Exception:
        log.exception("Failed to dispatch ProductAGI cycle worker")


__all__ = [
    "PRODUCT_AGENT_AGENT_NAME",
    "SUCCESSFUL_RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "create_cycle_run",
    "run_cycle_worker",
    "run_status_value",
    "trigger_product_agent_parallel",
]