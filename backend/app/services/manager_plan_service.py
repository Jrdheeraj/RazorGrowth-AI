"""
Manager Agent coordination service.

This is the service layer the central Manager Agent's HTTP surface uses. It
contains NO agent execution logic of its own:

  * planning calls :meth:`ManagerAgent.parse_goal` /
    :meth:`ManagerAgent.select_agents` / :meth:`ManagerAgent.build_execution_plan`
    and returns a validated, serialisable plan. It runs nothing;
  * workflow status reads the REAL ``AgentRun`` audit rows for the caller's
    merchant and reports what actually happened;
  * evaluation and final synthesis call
    :meth:`ManagerAgent.evaluate_results` / :meth:`ManagerAgent.build_final_report`
    so the Manager's interpretation rules have exactly one implementation.

Deliberate design decisions:

* **No new table.** The plan is a deterministic function of
  ``(objective, window_days, registry)``, and the orchestrator already
  persists the objective into ``AgentRun.input_summary``. A workflow is
  therefore reconstructed from real rows instead of a second stored copy,
  which means a plan can never drift out of sync with what was executed.
* **Honest about durability.** ``AgentRun`` rows are progress records. They
  are not a resumable checkpoint and an interrupted cycle is not continued
  after a process restart. The API says so explicitly rather than implying
  crash recovery that does not exist.
* **No approval authority.** Nothing here approves, executes or bypasses a
  guardrail; proposed actions stay in the Phase 4 approval workflow.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.agents.manager_agent import ManagerAgent
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import AgentActionStatus, AgentRunStatus
from backend.app.services.agent_run_service import AgentRunService

log = logging.getLogger(__name__)


#: Statuses that mean "the cycle is still in flight". Anything else is final.
ACTIVE_RUN_STATUSES = (AgentRunStatus.running,)


class ManagerWorkflowNotFound(LookupError):
    """Raised when a workflow id has no rows for the calling merchant."""


class ManagerCoordinationService:
    def __init__(self, db: Session, *, llm: Any = None) -> None:
        self.db = db
        self.llm = llm
        # One shared instance: the Manager holds no per-run state that would
        # make a second instance behave differently.
        self.manager = ManagerAgent()

    # ------------------------------------------------------------------ #
    # roster
    # ------------------------------------------------------------------ #

    def roster(self) -> dict[str, Any]:
        """Live registry contents. Counts come from the registry, never a constant."""
        from backend.app.agents.registry import DOMAIN_SPECIALIST_AGENTS, MAIN_GROWTH_TEAM_AGENTS

        agents = self.manager.discover_registered_agents()
        return {
            "agent_count": len(agents),
            "agents": agents,
            "main_growth_team": sorted(MAIN_GROWTH_TEAM_AGENTS),
            "domain_specialists": sorted(DOMAIN_SPECIALIST_AGENTS),
        }

    # ------------------------------------------------------------------ #
    # planning (no execution)
    # ------------------------------------------------------------------ #

    def build_plan(
        self,
        *,
        merchant_id: uuid.UUID,
        objective: str,
        window_days: int = 30,
        constraints: list[str] | None = None,
        budget: float | None = None,
        deadline: str | None = None,
        proposed_tasks: list[dict[str, Any]] | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Produce a validated execution plan for a merchant goal.

        Returns the plan WITHOUT running anything. The caller executes later by
        passing ``workflow_id`` to the existing orchestrator endpoint, so the
        cycle's audit rows correlate with the plan that produced them.
        """
        from backend.app.agents.base import AgentContext
        from backend.app.services.rag_context import RAGContextService

        params: dict[str, Any] = {"objective": objective, "window_days": window_days}
        if constraints:
            params["constraints"] = list(constraints)
        if budget is not None:
            params["budget"] = budget
        if deadline:
            params["deadline"] = deadline

        # Real merchant evidence, so the plan can state honestly whether the
        # goal is answerable from this merchant's own data.
        rag: dict[str, Any]
        try:
            rag = RAGContextService(self.db).build(
                merchant_id, objective, window_days=window_days
            )
        except Exception:  # noqa: BLE001 - planning must degrade, not crash
            log.exception("RAG context build failed; planning without evidence")
            rag = {"status": "unavailable"}

        ctx = AgentContext(
            db=self.db,
            merchant_id=merchant_id,
            mode="plan",
            params=params,
            llm=self.llm,
            embedding_provider=None,
            shared={"rag_context": rag},
        )

        goal = self.manager.parse_goal(ctx)
        # Merchant-stated constraints are recorded verbatim alongside the
        # parsed ones. They can never widen a guardrail.
        for extra in constraints or ():
            if extra not in goal["constraints"]:
                goal["constraints"].append(str(extra))

        selection = self.manager.select_agents(goal)
        selection["_roster"] = self.manager.discover_registered_agents()

        plan = self.manager.build_execution_plan(
            ctx=ctx,
            goal=goal,
            selection=selection,
            workflow_id=workflow_id or uuid.uuid4().hex,
            proposed_tasks=proposed_tasks,
        )
        plan["executed"] = False
        plan["requires_human_approval_for_actions"] = True
        # Surface selection reasoning for the merchant-facing plan view.
        plan["selection"] = [
            {"agent_id": s["agent_id"], "reason": s["reason"], "matched_tools": s["matched_tools"]}
            for s in selection.get("selected", ())
        ]
        # On-topic specialists that expose no implemented catalog tool. Reported
        # so the merchant is told why, e.g., a design goal did not route to the
        # Designer Agent rather than the platform quietly ignoring it.
        plan["limitations"] = list(selection.get("unavailable_specialists") or ())
        plan.pop("_roster", None)
        return plan

    # ------------------------------------------------------------------ #
    # workflow status from real audit rows
    # ------------------------------------------------------------------ #

    def get_workflow(self, *, merchant_id: uuid.UUID, workflow_id: str) -> dict[str, Any]:
        """
        Reconstruct a workflow from the caller's real ``AgentRun`` rows.

        Tenant-scoped: a workflow belonging to another merchant resolves to the
        same "not found" as one that never existed, so there is no existence
        leak across workspaces.
        """
        runs = AgentRunService(self.db).list_runs(
            merchant_id, orchestrator_run_id=workflow_id, limit=200
        )
        if not runs:
            raise ManagerWorkflowNotFound(workflow_id)

        runs = sorted(runs, key=lambda r: r.started_at)
        mode = runs[0].mode
        objective = self._objective_from_runs(runs)
        window_days = self._window_from_runs(runs)

        agents_run = [self._agent_entry(r) for r in runs]
        totals = {
            "opportunities_created": sum(a["opportunities_created"] for a in agents_run),
            "actions_proposed": sum(a["actions_proposed"] for a in agents_run),
            "insights_generated": sum(a["insights_generated"] for a in agents_run),
            "signals_detected": sum(a["signals_detected"] for a in agents_run),
            "experiments_proposed": sum(a["experiments_proposed"] for a in agents_run),
            "agents_executed": len(agents_run),
            "failed_agents": sum(1 for a in agents_run if a["status"] == "failed"),
        }

        evaluation = self.manager.evaluate_results(agents_run)

        # The plan is recomputed from the SAME inputs the cycle used, so the
        # merchant sees the intended delegation next to what really ran.
        plan: dict[str, Any] | None
        try:
            plan = self.build_plan(
                merchant_id=merchant_id,
                objective=objective or "growth opportunity analysis",
                window_days=window_days,
                workflow_id=workflow_id,
            )
        except Exception:  # noqa: BLE001 - a plan must never hide the real run
            log.exception("Plan reconstruction failed for workflow %s", workflow_id)
            plan = None

        report = self.manager.build_final_report(
            goal=plan.get("goal") if plan else {"goal": objective, "blocked_reasons": []},
            plan=plan or {},
            summary={"status": evaluation["outcome"], "totals": totals, "agents": agents_run},
        )

        return {
            "workflow_id": workflow_id,
            "merchant_id": str(merchant_id),
            "mode": mode,
            "status": self._workflow_status(runs, evaluation),
            "objective": objective,
            "agents_run": agents_run,
            "totals": totals,
            "plan": plan,
            "evaluation": evaluation,
            "report": report,
            # Honest capability statement, not an implied guarantee.
            "durable_checkpoint": False,
            "recoverable_after_restart": False,
            "recovery_note": (
                "AgentRun rows are progress records. They are not a resumable checkpoint; "
                "an interrupted cycle is not automatically continued after a process restart."
            ),
        }

    @staticmethod
    def _workflow_status(runs: list[AgentRun], evaluation: dict[str, Any]) -> str:
        if any(r.status in ACTIVE_RUN_STATUSES for r in runs):
            return "running"
        return evaluation.get("outcome", "unknown")

    @staticmethod
    def _agent_entry(run: AgentRun) -> dict[str, Any]:
        return {
            "agent": run.agent_name,
            "status": str(getattr(run.status, "value", run.status)),
            "opportunities_created": run.opportunities_created,
            "actions_proposed": run.actions_proposed,
            "insights_generated": run.insights_generated,
            "signals_detected": run.signals_detected,
            "experiments_proposed": run.experiments_proposed,
            "tools_used": list(run.tools_used or []),
            "errors": list(run.errors or []),
            "latency_ms": {"total": run.total_latency_ms, "llm": run.llm_latency_ms, "db": run.db_latency_ms, "tool": run.tool_latency_ms},
            "output": dict(run.output_summary or {}),
            "started_at": str(run.started_at),
            "completed_at": str(run.completed_at) if run.completed_at else None,
        }

    @staticmethod
    def _params_from_runs(runs: list[AgentRun]) -> dict[str, Any]:
        """First non-empty params dict the orchestrator persisted."""
        for run in runs:
            summary = run.input_summary or {}
            params = summary.get("params")
            if isinstance(params, dict) and params:
                return params
        return {}

    @classmethod
    def _objective_from_runs(cls, runs: list[AgentRun]) -> str | None:
        value = cls._params_from_runs(runs).get("objective")
        return str(value) if value else None

    @classmethod
    def _window_from_runs(cls, runs: list[AgentRun]) -> int:
        value = cls._params_from_runs(runs).get("window_days")
        try:
            return max(1, min(365, int(value)))
        except (TypeError, ValueError):
            return 30

    # ------------------------------------------------------------------ #
    # real metrics (never invented)
    # ------------------------------------------------------------------ #

    def metrics(self, *, merchant_id: uuid.UUID, window_days: int = 30) -> dict[str, Any]:
        """
        Dashboard figures, each computed from real rows.

        Anything that cannot be computed is reported as ``None`` with a stated
        reason instead of being replaced with a plausible number.
        """
        from datetime import datetime, timedelta, timezone

        since = datetime.now(timezone.utc) - timedelta(days=window_days)

        base = select(AgentRun).where(AgentRun.merchant_id == merchant_id)
        window_runs = list(self.db.scalars(base.where(AgentRun.started_at >= since)).all())

        agents_stmt = (
            select(AgentRun.agent_name, func.count(func.distinct(AgentRun.agent_name)))
            .where(AgentRun.merchant_id == merchant_id)
            .group_by(AgentRun.agent_name)
        )
        distinct_agents = int(sum(int(c) for _, c in self.db.execute(agents_stmt).all()))

        completed = [r for r in window_runs if r.status == AgentRunStatus.completed]
        active_workflows = len(
            {
                r.orchestrator_run_id
                for r in window_runs
                if r.status in ACTIVE_RUN_STATUSES and r.orchestrator_run_id
            }
        )
        total_workflows = len(
            {
                r.orchestrator_run_id
                for r in window_runs
                if r.orchestrator_run_id
            }
        )

        pending_stmt = (
            select(func.count(AgentAction.id))
            .where(
                AgentAction.merchant_id == merchant_id,
                AgentAction.status == AgentActionStatus.requested,
            )
        )
        awaiting = int(self.db.scalar(pending_stmt) or 0)

        # "Tasks completed" is agent runs that actually completed. It is not
        # a fabricated task counter: no task table is invented here.
        tasks_completed = len(completed)

        return {
            "merchant_id": str(merchant_id),
            "agents_coordinated": distinct_agents,
            "tasks_completed": tasks_completed,
            "awaiting_approval": awaiting,
            "active_workflows": active_workflows,
            "total_workflows": total_workflows,
            "window_days": window_days,
            "metrics_available": True,
            "unavailable_reasons": [],
        }

    # ------------------------------------------------------------------ #
    # pending proposals
    # ------------------------------------------------------------------ #

    def pending_actions(
        self,
        *,
        merchant_id: uuid.UUID,
        limit: int = 50,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Pending actions with their real originating agent and workflow.

        Read-only. Approval stays exclusively in the existing authorized
        endpoints; nothing here transitions an action's state.
        """
        stmt = (
            select(AgentAction)
            .where(
                AgentAction.merchant_id == merchant_id,
                AgentAction.status == AgentActionStatus.requested,
            )
            .order_by(AgentAction.created_at.desc())
            .limit(limit)
        )
        rows = list(self.db.scalars(stmt).all())

        # Attach workflow correlation when the action records one, so the
        # merchant can trace a proposal back to the cycle that produced it.
        by_workflow: dict[str, list[str]] = {}
        run_stmt = select(AgentRun).where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.orchestrator_run_id.isnot(None),
        )
        for run in self.db.scalars(run_stmt).all():
            key = str(run.orchestrator_run_id)
            by_workflow.setdefault(key, [])
            if run.agent_name not in by_workflow[key]:
                by_workflow[key].append(run.agent_name)

        actions: list[dict[str, Any]] = []
        for row in rows:
            payload = row.input_payload if isinstance(row.input_payload, dict) else {}
            wf = str(payload.get("orchestrator_run_id") or payload.get("analysis_cycle_id") or "") or None
            if wf and workflow_id and wf != workflow_id:
                continue
            actions.append(
                {
                    "id": str(row.id),
                    "action_type": str(getattr(row.action_type, "value", row.action_type)),
                    "status": str(getattr(row.status, "value", row.status)),
                    "requested_by": row.requested_by,
                    "origin_agent": self._origin_agent(row.requested_by),
                    "workflow_id": wf,
                    "workflow_agents": by_workflow.get(wf or "", []),
                    "created_at": str(row.created_at),
                    "input_payload": payload,
                    "approvable": True,
                    "approved_by_manager": False,
                }
            )

        return {
            "merchant_id": str(merchant_id),
            "actions": actions,
            "pending_count": len(actions),
        }

    @staticmethod
    def _origin_agent(requested_by: str | None) -> str | None:
        """Map 'agent:FooAgent' back to the agent that proposed the action."""
        if not requested_by:
            return None
        raw = str(requested_by)
        return raw.split("agent:", 1)[1] if raw.startswith("agent:") else raw
