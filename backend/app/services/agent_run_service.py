"""
AgentRun service — Phase 5 Features 14 & 15 (audit trail + observability).

Every specialised-agent execution is recorded BEFORE it starts
(status=running) and finalised afterwards, so crashes are visible.
Stored payloads contain structured summaries only — never prompts with
credentials, API keys, or payment credentials (there is no code path
that could place them here; keys live exclusively in Settings).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.campaign import Campaign
from backend.app.models.enums import AgentActionStatus, AgentRunStatus

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── lifecycle ────────────────────────────────────────────────────────

    def start_run(
        self,
        *,
        merchant_id: uuid.UUID | None,
        agent_name: str,
        orchestrator_run_id: str,
        mode: str = "deep",
        input_summary: dict[str, Any] | None = None,
    ) -> AgentRun:
        settings = get_settings()
        run = AgentRun(
            merchant_id=merchant_id,
            orchestrator_run_id=orchestrator_run_id,
            agent_name=agent_name,
            status=AgentRunStatus.running,
            mode=mode,
            started_at=_utcnow(),
            input_summary=input_summary or {},
            llm_provider=settings.LLM_PROVIDER if settings.LLM_API_KEY or settings.GROQ_API_KEY else None,
            llm_model=(
                settings.GROQ_MODEL
                if settings.LLM_PROVIDER.lower() == "groq"
                else settings.LLM_MODEL
            )
            if settings.LLM_API_KEY or settings.GROQ_API_KEY
            else "not-configured",
        )
        self.db.add(run)
        self.db.flush()
        return run

    def complete_run(self, run: AgentRun, result: Any) -> AgentRun:
        from backend.app.models.enums import AgentRunStatus as S

        run.status = (
            S.completed if result.status == "completed" else S.failed
        )
        run.completed_at = _utcnow()
        run.output_summary = dict(result.output) if result.output else {}
        run.tools_used = list(result.tools_used)
        run.opportunities_created = result.opportunities_created
        run.actions_proposed = result.actions_proposed
        run.errors = list(result.errors)
        run.total_latency_ms = int(result.total_ms)
        run.llm_latency_ms = int(result.llm_ms)
        run.db_latency_ms = int(result.db_ms)
        run.tool_latency_ms = int(result.tool_ms)
        self.db.flush()
        return run

    # ── queries ──────────────────────────────────────────────────────────

    def list_runs(
        self,
        merchant_id: uuid.UUID | None = None,
        *,
        orchestrator_run_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
        if merchant_id is not None:
            stmt = stmt.where(AgentRun.merchant_id == merchant_id)
        if orchestrator_run_id is not None:
            stmt = stmt.where(AgentRun.orchestrator_run_id == orchestrator_run_id)
        return list(self.db.scalars(stmt).all())

    def get_run(
        self, run_id: uuid.UUID, *, merchant_id: uuid.UUID | None = None
    ) -> AgentRun | None:
        """Merchant-scoped fetch when a merchant context is supplied."""
        run = self.db.get(AgentRun, run_id)
        if run is None:
            return None
        if merchant_id is not None and run.merchant_id != merchant_id:
            return None
        return run

    # ── observability summary (Feature 15) ───────────────────────────────

    def observability_summary(
        self, merchant_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        stmt = (
            select(
                AgentRun.status,
                func.count(AgentRun.id),
                func.coalesce(func.sum(AgentRun.total_latency_ms), 0),
                func.coalesce(func.sum(AgentRun.llm_latency_ms), 0),
                func.coalesce(func.sum(AgentRun.db_latency_ms), 0),
                func.coalesce(func.sum(AgentRun.tool_latency_ms), 0),
                func.coalesce(func.sum(AgentRun.opportunities_created), 0),
                func.coalesce(func.sum(AgentRun.actions_proposed), 0),
            ).group_by(AgentRun.status)
        )
        if merchant_id is not None:
            stmt = stmt.where(AgentRun.merchant_id == merchant_id)
        rows = self.db.execute(stmt).all()

        by_status: dict[str, int] = {}
        totals = {
            "total_latency_ms": 0, "llm_latency_ms": 0,
            "db_latency_ms": 0, "tool_latency_ms": 0,
            "opportunities_discovered": 0, "actions_proposed": 0,
        }
        for status, count, total_ms, llm_ms, db_ms, tool_ms, opps, acts in rows:
            key = str(getattr(status, "value", status))
            by_status[key] = int(count)
            totals["total_latency_ms"] += int(total_ms)
            totals["llm_latency_ms"] += int(llm_ms)
            totals["db_latency_ms"] += int(db_ms)
            totals["tool_latency_ms"] += int(tool_ms)
            totals["opportunities_discovered"] += int(opps)
            totals["actions_proposed"] += int(acts)

        action_counts: dict[str, int] = {}
        act_stmt = (
            select(AgentAction.status, func.count(AgentAction.id))
            .group_by(AgentAction.status)
        )
        if merchant_id is not None:
            act_stmt = act_stmt.where(AgentAction.merchant_id == merchant_id)
        for status, count in self.db.execute(act_stmt).all():
            action_counts[str(getattr(status, "value", status))] = int(count)

        measured_stmt = select(func.coalesce(func.sum(Campaign.actual_revenue), 0))
        if merchant_id is not None:
            measured_stmt = measured_stmt.where(Campaign.merchant_id == merchant_id)
        measured_revenue = Decimal_or_zero(self.db.scalar(measured_stmt))

        total_runs = sum(by_status.values())
        return {
            "agents_registered": len(_registered_agent_names()),
            "runs_by_status": by_status,
            "successful_runs": by_status.get("completed", 0),
            "failed_runs": by_status.get("failed", 0),
            "total_runs": total_runs,
            "latency": totals,
            "actions_by_status": action_counts,
            "actions_approved": action_counts.get("approved", 0)
            + action_counts.get("executing", 0)
            + action_counts.get("completed", 0),
            "actions_rejected": action_counts.get("rejected", 0),
            "measured_revenue_total": float(measured_revenue),
        }


def Decimal_or_zero(v: Any):
    from decimal import Decimal

    try:
        return Decimal(str(v))
    except Exception:  # pragma: no cover
        return Decimal("0")


def _registered_agent_names() -> list[str]:
    from backend.app.agents.registry import AGENT_INSTANCES

    return list(AGENT_INSTANCES.keys())
