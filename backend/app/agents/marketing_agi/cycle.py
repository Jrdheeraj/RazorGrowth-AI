"""AI Team shared-cycle integration for the Marketing Agent.

This module is the ONLY bridge between the AI Team orchestrator
(POST /api/agents/run, mode="team") and the autonomous MarketingAGI
loop. It provides:

  create_cycle_run(db, merchant_id, objective, cycle_id)
      Idempotently create the MarketingAGI run row belonging to ``cycle_id``
      (the orchestrator_run_id shared with sibling agents). Calling it
      twice with the same cycle returns the existing row — exactly one
      Marketing Agent execution per analysis cycle. The LLM identity
      (Groq-first, backend-only key) is stamped on the row.

  run_cycle_worker(session_factory, run_id, merchant_id, objective,
                   cycle_id)
      Execute the bounded MarketingAGI loop on a worker session and close
      out the AgentRun audit row. Never raises: Groq/loop failures mark
      the run failed/degraded without touching sibling agents.

  trigger_marketing_agi_parallel(..., dispatch=...)
      Start the worker without waiting for it (default: daemon thread),
      so the Marketing Agent runs in parallel with the other AI Team
      agents and never blocks them. ``dispatch`` is injectable for tests.

Tenant isolation: the merchant id always comes from the backend
authenticated context; the model can never override it (tool arguments
are sanitized in agent.sanitize_tool_args, and the worker session is
bound to the given merchant id only).
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MARKETING_AGI_AGENT_NAME = "MarketingAGI"


def create_cycle_run(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
) -> Any:
    """Create (or return the existing) MarketingAGI run for a cycle.

    Idempotency: at most one run per (merchant, cycle). Re-entrant calls
    — retries, double-clicks, re-dispatch — return the existing row.
    """
    from backend.app.models.marketing_agi import MarketingAGIRun

    existing = db.scalar(
        select(MarketingAGIRun).where(
            MarketingAGIRun.merchant_id == merchant_id,
            MarketingAGIRun.analysis_cycle_id == cycle_id,
        )
    )
    if existing is not None:
        return existing

    from backend.app.agents.marketing_agi.llm import llm_identity

    _, provider, model = llm_identity()
    run_row = MarketingAGIRun(
        merchant_id=merchant_id,
        objective=objective,
        status="queued",
        phase="load_context",
        analysis_cycle_id=cycle_id,
        llm_provider=provider,
        llm_model=model,
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
    """Close the AgentRun audit row so the AI Team page shows live status."""
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.enums import AgentRunStatus

    row = db.scalar(
        select(AgentRun).where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.orchestrator_run_id == cycle_id,
            AgentRun.agent_name == MARKETING_AGI_AGENT_NAME,
        )
    )
    if row is None:
        return
    try:
        row.status = AgentRunStatus(status)
    except ValueError:
        row.status = AgentRunStatus.failed
    from datetime import datetime, timezone

    row.completed_at = datetime.now(timezone.utc)
    if output is not None:
        row.output_summary = output
    if errors is not None:
        row.errors = errors
    db.flush()


def run_cycle_worker(
    session_factory: Any,
    run_id: uuid.UUID,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
) -> None:
    """Execute the Marketing Agent loop for a cycle. Never raises."""
    db: Session = session_factory()
    try:
        from backend.app.models.marketing_agi import MarketingAGIRun
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.agents.marketing_agi.llm import build_marketing_llm

        run_row = db.get(MarketingAGIRun, run_id)
        if run_row is None or run_row.merchant_id != merchant_id:
            log.error(
                "MarketingAGI cycle worker: run %s not found for merchant", run_id
            )
            return
        try:
            llm = build_marketing_llm()
        except Exception:
            log.exception("MarketingAGI cycle worker: Groq setup failed")
            llm = None
        embedder = None
        try:
            from backend.app.core.config import get_settings

            settings = get_settings()
            if settings.LLM_API_KEY:
                from backend.app.ai.embeddings.provider import (
                    build_embedding_provider,
                )

                embedder = build_embedding_provider(
                    provider=settings.EMBEDDING_PROVIDER,
                    api_key=settings.LLM_API_KEY,
                    model=settings.EMBEDDING_MODEL,
                )
        except Exception:
            log.warning("MarketingAGI cycle worker: embedder unavailable")
        agent = MarketingAGI(db, merchant_id, llm=llm, embedding_provider=embedder)
        agent.run(run_row, objective, analysis_cycle_id=cycle_id)
        state = run_row.state or {}
        output = {
            "status": run_row.status,
            "phase": run_row.phase,
            "workflow": state.get("workflow"),
            "evidence_count": len(state.get("evidence", [])),
            "tool_calls": state.get("tool_call_count", 0),
            "llm_decisions": len(state.get("llm_decisions", [])),
            "campaign": state.get("campaign_draft"),
            "prepared_action": state.get("prepared_action"),
        }
        terminal = run_row.status in {
            "waiting_approval", "completed", "blocked", "failed", "cancelled",
        }
        _complete_audit_row(
            db,
            merchant_id=merchant_id,
            cycle_id=cycle_id,
            status="completed" if terminal else "failed",
            output=output,
            errors=list(run_row.errors or []),
        )
        db.commit()
    except Exception:
        log.exception("MarketingAGI cycle worker crashed for run %s", run_id)
        db.rollback()
        try:
            from backend.app.models.marketing_agi import MarketingAGIRun

            run_row = db.get(MarketingAGIRun, run_id)
            if run_row is not None and run_row.status in {"queued", "running"}:
                from datetime import datetime, timezone

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
            db.rollback()
    finally:
        db.close()


def trigger_marketing_agi_parallel(
    session_factory: Any,
    *,
    merchant_id: uuid.UUID,
    objective: str,
    cycle_id: str,
    run_id: uuid.UUID,
    dispatch: Callable[[Callable[[], None]], None] | None = None,
) -> None:
    """Start the cycle worker without blocking the caller.

    The Marketing Agent executes independently and in parallel with the
    sibling AI Team agents. Dispatch failures are swallowed: the AI Team
    analysis must never fail because the Marketing Agent could not start.
    """
    def _work() -> None:
        run_cycle_worker(session_factory, run_id, merchant_id, objective, cycle_id)

    try:
        if dispatch is not None:
            dispatch(_work)
        else:
            thread = threading.Thread(
                target=_work,
                name=f"marketing-agi-cycle-{cycle_id[:8]}",
                daemon=True,
            )
            thread.start()
    except Exception:
        log.exception("Failed to dispatch MarketingAGI cycle worker")
