"""
GrowthAgentOrchestrator — Phase 5 Feature 1.

Runs specialised agents in a CONTROLLED order, isolates failures via
savepoints so one broken agent never corrupts or aborts the rest,
deduplicates and ranks opportunities, feeds proposed actions into the
existing Phase 4 approval workflow, records an AgentRun audit row per
agent, and returns partial results.

Orchestration strategy (Feature 26):
  mode="fast"  → memory(load) · discovery · payment_recovery · prioritization
                  (cheap signal-level pass; no LLM required)
  mode="deep"  → full pipeline including customer intelligence, campaign
                  strategy, revenue optimization, experiments, and a final
                  memory write.
  mode="growth_team" → Main AI Growth Team: Manager delegates to
                  Marketing, Product, Designer, Software agents, then
                  synthesizes via Agent Debate.

The orchestrator NEVER approves, rejects, executes, or bypasses
guardrails. Its only bridge to execution is Phase 4's create_action()
which lands in 'requested' state.
"""
from __future__ import annotations

import logging
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.registry import AGENT_INSTANCES, MAIN_GROWTH_TEAM_AGENTS
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.merchant import Merchant
from backend.app.services.workflow_run_service import (
    EXECUTION_ENGINE_LANGGRAPH,
    EXECUTION_ENGINE_LEGACY,
    KNOWN_EXECUTION_ENGINES,
    PlanIncompatible,
    is_cancel_requested,
    ReuseVerdict,
    StaleLeaseError,
    WorkflowNotFound,
    WorkflowNotResumable,
    WorkflowOwnershipError,
    WorkflowRunService,
    current_workflow,
    is_resumable,
    step_key as step_key_for,
)

log = logging.getLogger(__name__)

#: A cycle whose owning heartbeat is older than this is treated as DEAD and
#: may be taken over. Kept short so a crashed cycle is recoverable promptly,
#: and long enough that a merely slow agent is never declared dead. A worker
#: that is alive and merely quiet must heartbeat (see WorkflowRunService).
STALE_TAKEOVER_SECONDS = 120

FAST_PLAN = (
    ("GrowthMemoryAgent", {"phase": "load"}),
    ("GrowthDiscoveryAgent", {}),
    ("PaymentRecoveryAgent", {}),
    ("OpportunityPrioritizationAgent", {}),
)

DEEP_PLAN = (
    ("GrowthMemoryAgent", {"phase": "load"}),
    ("GrowthDiscoveryAgent", {}),
    ("CustomerIntelligenceAgent", {}),
    ("PaymentRecoveryAgent", {}),
    ("CampaignStrategistAgent", {}),
    ("RevenueOptimizationAgent", {}),
    ("ExperimentAgent", {}),
    ("OpportunityPrioritizationAgent", {}),
)

# Phase E: Main AI Growth Team orchestration with 4-Round Multi-Agent Debate
GROWTH_TEAM_PLAN = (
    ("GrowthMemoryAgent", {"phase": "load"}),
    ("ManagerAgent", {"phase": "delegate"}),
    # Round 1: Individual Investigation
    ("MarketingAgent", {"phase": "investigate"}),
    ("ProductAgent", {"phase": "investigate"}),
    ("DesignerAgent", {"phase": "investigate"}),
    ("SoftwareAgent", {"phase": "investigate"}),
    # Round 2: Cross-Examination / Challenge
    ("MarketingAgent", {"phase": "cross_examine"}),
    ("ProductAgent", {"phase": "cross_examine"}),
    ("DesignerAgent", {"phase": "cross_examine"}),
    ("SoftwareAgent", {"phase": "cross_examine"}),
    # Round 3: Rebuttal
    ("MarketingAgent", {"phase": "rebut"}),
    ("ProductAgent", {"phase": "rebut"}),
    ("DesignerAgent", {"phase": "rebut"}),
    ("SoftwareAgent", {"phase": "rebut"}),
    # Round 4: Final Executive Synthesis & Consensus
    ("ManagerAgent", {"phase": "synthesize"}),
    ("GrowthMemoryAgent", {"phase": "persist"}),
)

# AI Team Workspace: Coordinated 13-agent collaborative business pipeline
AI_TEAM_PLAN = (
    ("GrowthMemoryAgent", {"phase": "load"}),
    ("GrowthDiscoveryAgent", {}),
    ("CustomerIntelligenceAgent", {}),
    ("RevenueOptimizationAgent", {}),
    ("PaymentRecoveryAgent", {}),
    ("MarketingAgent", {"phase": "work"}),
    ("ProductAgent", {"phase": "work"}),
    ("CampaignStrategistAgent", {}),
    ("DesignerAgent", {"phase": "work"}),
    ("ExperimentAgent", {}),
    ("OpportunityPrioritizationAgent", {}),
    ("SoftwareAgent", {"phase": "work"}),
    ("ManagerAgent", {"phase": "coordinate"}),
    ("GrowthMemoryAgent", {"phase": "persist"}),
)


@dataclass
class OrchestrationSummary:
    orchestrator_run_id: str
    merchant_id: str
    mode: str
    status: str = "completed"
    debate_id: str | None = None
    action_plan: dict[str, Any] | None = None
    agents_run: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    ranked_opportunities: list[dict[str, Any]] = field(default_factory=list)
    #: True when this invocation continued an existing cycle rather than
    #: starting a new one. Distinguishes recovery from a fresh analysis.
    resumed: bool = False
    #: The durable workflow row id, so callers can correlate the cycle.
    workflow_id: str | None = None
    #: Steps replayed from persisted results rather than re-executed.
    resumed_steps: list[dict[str, Any]] = field(default_factory=list)
    #: Steps whose persisted result could not be shown to be safe. Never reused
    #: and never retried automatically -- they need reconciliation.
    needs_reconciliation: list[str] = field(default_factory=list)
    #: Plan index at which a cancellation was observed, or None if the cycle ran
    #: to a normal outcome.
    cancelled_at_step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "orchestrator_run_id": self.orchestrator_run_id,
            "merchant_id": self.merchant_id,
            "mode": self.mode,
            "status": self.status,
            "debate_id": self.debate_id,
            "action_plan": self.action_plan,
            "agents": self.agents_run,
            "totals": self.totals,
            "ranked_opportunities": self.ranked_opportunities,
            "resumed": self.resumed,
            "workflow_id": self.workflow_id,
            "resumed_steps": self.resumed_steps,
            "needs_reconciliation": self.needs_reconciliation,
            "cancelled_at_step": self.cancelled_at_step,
        }


class MerchantNotFoundError(LookupError):
    pass


class GrowthAgentOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        llm: Any = None,
        embedding_provider: Any = None,
        run_service: Any = None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.embedding_provider = embedding_provider
        if run_service is None:
            from backend.app.services.agent_run_service import AgentRunService

            run_service = AgentRunService(db)
        self.runs = run_service
        # Workflow-execution state (a step's start row and its outcome) is
        # written through its OWN Session on the same Engine, so recording it
        # never has to commit -- or be committed alongside -- the orchestrator's
        # merchant business transaction.
        #
        # On PostgreSQL and file-backed SQLite this is a separate connection.
        # On ``sqlite:///:memory:`` with StaticPool every session shares one
        # connection, so the boundary is not independent there; the PostgreSQL
        # suite is what actually proves it.
        self._state_sf = sessionmaker(
            bind=db.get_bind(), expire_on_commit=False, autoflush=False
        )

    def _state_session(self) -> Session:
        """A fresh dedicated session for one step's execution records."""
        return self._state_sf()

    # ── public API ───────────────────────────────────────────────────────

    def run(
        self,
        merchant_id: uuid.UUID,
        *,
        mode: str = "deep",
        params: dict[str, Any] | None = None,
        run_id: str | None = None,
        use_langgraph: bool = True,
    ) -> OrchestrationSummary:
        """
        Execute one multi-agent cycle.

        Defaults to LangGraph StateGraph execution (use_langgraph=True), preserving
        all existing API contracts, leases, recovery, cancellation, and failure isolation.

        Re-using ``run_id`` now means "continue THIS cycle", not "start a
        parallel one": the ``(merchant_id, run_id)`` unique constraint resolves
        the id to the existing durable workflow, and completed steps are reused
        rather than re-executed. A caller that wants a genuinely fresh cycle
        simply omits ``run_id``.

        To continue an interrupted cycle explicitly (and get the refusal
        reasons rather than silent reuse), call ``resume()``.
        """
        if use_langgraph:
            return self.run_with_langgraph(
                merchant_id,
                mode=mode,
                params=params,
                run_id=run_id,
            )

        if mode not in ("fast", "deep", "growth_team", "team"):
            raise ValueError("mode must be 'fast', 'deep', 'growth_team', or 'team'")
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise MerchantNotFoundError(f"Merchant {merchant_id} not found")

        # Shared analysis cycle: the AI Team route supplies run_id for
        # mode="team" so every agent_runs row (and the Marketing/Product
        # employees' linked executions) carry the same cycle id. A caller that
        # omits it gets a fresh cycle, preserving legacy behaviour.
        orchestrator_run_id = run_id or uuid.uuid4().hex
        plan = _plan_for(mode)

        wf = WorkflowRunService(self.db)
        workflow, created = wf.start_workflow(
            merchant_id=merchant_id,
            run_id=orchestrator_run_id,
            mode=mode,
            plan=plan,
            execution_engine=EXECUTION_ENGINE_LEGACY,
        )
        if created:
            # Make the cycle visible to other processes before any step runs,
            # so a crash always leaves a discoverable, resumable record.
            self.db.commit()

        # Claim ownership IMMEDIATELY, before any step, and carry the resulting
        # fencing generation into every protected write. Without a generation a
        # worker cannot be distinguished from one that has since lost the cycle.
        generation = wf.claim(
            workflow,
            owner=f"run:{uuid.uuid4().hex[:12]}",
            # A cycle created moments ago has no lease at all and is ours by
            # construction; an existing one must respect a live owner.
            stale_after_seconds=None if created else STALE_TAKEOVER_SECONDS,
        )
        self.db.commit()

        if created:
            pass
        else:
            # Taking over an EXISTING cycle. Steps still marked running are
            # closed out as `interrupted` -- but ONLY when the owner's heartbeat
            # is cold, because a step under a live owner may be genuinely
            # mid-flight and must not be disturbed. Callers wanting the
            # lease-guaranteed path (and its explicit refusal reasons) should
            # use resume().
            heartbeat = workflow.heartbeat_at
            cold = heartbeat is None or _as_utc(heartbeat) <= (
                datetime.now(timezone.utc) - timedelta(seconds=STALE_TAKEOVER_SECONDS)
            )
            if cold:
                interrupted = wf.mark_interrupted_steps(
                    workflow.id, reason="interrupted_by_prior_process_exit"
                )
                if interrupted:
                    log.warning(
                        "Workflow %s: closed %d interrupted step(s): %s",
                        orchestrator_run_id, len(interrupted), interrupted,
                    )
                    self.db.commit()

        return self._execute(
            merchant_id=merchant_id,
            mode=mode,
            plan=plan,
            orchestrator_run_id=orchestrator_run_id,
            params=params,
            workflow_id=workflow.id,
            wf=wf,
            resumed=not created,
            generation=generation,
        )

    def run_with_langgraph(
        self,
        merchant_id: uuid.UUID,
        *,
        mode: str = "deep",
        params: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> OrchestrationSummary:
        """Execute the multi-agent growth cycle via compiled LangGraph StateGraph.

        Wires all 14 agents into a stateful, typed execution graph with
        checkpointing, cancellation, and lease fencing.
        """
        if mode not in ("fast", "deep", "growth_team", "team"):
            raise ValueError("mode must be 'fast', 'deep', 'growth_team', or 'team'")
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise MerchantNotFoundError(f"Merchant {merchant_id} not found")

        orchestrator_run_id = run_id or uuid.uuid4().hex
        plan = _plan_for(mode)

        wf = WorkflowRunService(self.db)
        workflow, created = wf.start_workflow(
            merchant_id=merchant_id,
            run_id=orchestrator_run_id,
            mode=mode,
            plan=plan,
            execution_engine=EXECUTION_ENGINE_LANGGRAPH,
        )
        if created:
            self.db.commit()

        generation = wf.claim(
            workflow,
            owner=f"langgraph:{uuid.uuid4().hex[:12]}",
            stale_after_seconds=None if created else STALE_TAKEOVER_SECONDS,
        )
        self.db.commit()

        if not created:
            heartbeat = workflow.heartbeat_at
            cold = heartbeat is None or _as_utc(heartbeat) <= (
                datetime.now(timezone.utc) - timedelta(seconds=STALE_TAKEOVER_SECONDS)
            )
            if cold:
                interrupted = wf.mark_interrupted_steps(
                    workflow.id, reason="interrupted_by_prior_process_exit"
                )
                if interrupted:
                    log.warning(
                        "Workflow %s: closed %d interrupted step(s): %s",
                        orchestrator_run_id, len(interrupted), interrupted,
                    )
                    self.db.commit()

        return self._execute_langgraph(
            merchant_id=merchant_id,
            mode=mode,
            orchestrator_run_id=orchestrator_run_id,
            params=params,
            workflow_id=workflow.id,
            wf=wf,
            resumed=not created,
            generation=generation,
        )

    def _execute_langgraph(
        self,
        *,
        merchant_id: uuid.UUID,
        mode: str,
        orchestrator_run_id: str,
        params: dict[str, Any] | None,
        workflow_id: uuid.UUID,
        wf: WorkflowRunService,
        resumed: bool,
        generation: int,
    ) -> OrchestrationSummary:
        """Execute one already-claimed cycle through the LangGraph graph.

        Shared by a fresh LangGraph run and by recovery of a cycle whose
        recorded engine is ``langgraph``, so both use the same executor and the
        same final-state -> summary mapping. The CALLER owns the lease; this
        method never claims one.
        """
        from backend.app.ai.langgraph_orchestrator.executor import (
            LangGraphWorkflowExecutor,
        )

        executor = LangGraphWorkflowExecutor(
            self.db,
            llm=self.llm,
            embedding_provider=self.embedding_provider,
            run_service=wf,
        )
        final_state = executor.execute_workflow(
            merchant_id=merchant_id,
            mode=mode,
            orchestrator_run_id=orchestrator_run_id,
            params=params,
            workflow_id=workflow_id,
            resumed=resumed,
            generation=generation,
        )

        return OrchestrationSummary(
            orchestrator_run_id=orchestrator_run_id,
            merchant_id=str(merchant_id),
            mode=mode,
            status=final_state.get("status", "completed"),
            debate_id=final_state.get("debate_id"),
            action_plan=final_state.get("action_plan"),
            agents_run=final_state.get("agents_run", []),
            totals=final_state.get("totals", {}),
            ranked_opportunities=final_state.get("ranked_opportunities", []),
            resumed=resumed,
            workflow_id=str(workflow_id),
            resumed_steps=final_state.get("resumed_steps", []),
            needs_reconciliation=final_state.get("needs_reconciliation", []),
            cancelled_at_step=final_state.get("cancelled_at_step"),
        )

    # ── recovery ────────────────────────────────────────────────────────

    def resume(
        self,
        merchant_id: uuid.UUID,
        run_id: str,
        *,
        params: dict[str, Any] | None = None,
        lease_seconds: int = 900,
        stale_after_seconds: int = 120,
    ) -> OrchestrationSummary:
        """
        Continue an interrupted cycle from its persisted state.

        This is the supported recovery path. It reuses the SAME execution
        machinery as ``run()`` -- there is no second orchestrator -- and first:

          1. loads the durable workflow row, scoped to this merchant;
          2. verifies the stored plan still matches the requested plan (a
             changed plan is refused, never silently merged);
          3. refuses a cycle whose recorded execution engine is unknown, and
             otherwise resumes it on the SAME engine that created it
             (``langgraph`` -> graph executor, ``legacy``/NULL -> the legacy
             step loop);
          4. takes single-writer ownership via a compare-and-set lease, so a
             healthy worker is never taken over and two concurrent resumes
             cannot both proceed;
          5. closes out steps left ``running`` by the dead process, recording
             them as ``interrupted`` rather than leaving a silent orphan.

        Completed and partially-completed steps are REUSED from their persisted
        rows. Failed, blocked, skipped and interrupted steps are eligible for
        another attempt, written under an incremented ``attempt`` so the earlier
        history is preserved rather than overwritten.

        Raises ``WorkflowNotFound`` (also for another tenant's cycle),
        ``PlanIncompatible``, ``WorkflowNotResumable`` or
        ``WorkflowOwnershipError`` instead of guessing.
        """
        wf = WorkflowRunService(self.db)
        workflow = wf.get_workflow_row(merchant_id=merchant_id, run_id=run_id)

        mode = workflow.mode
        if mode not in ("fast", "deep", "growth_team", "team"):
            raise PlanIncompatible(
                f"workflow {run_id} has unsupported mode {mode!r}"
            )
        plan = _plan_for(mode)

        # Refuse to graft a new plan's results onto old history.
        wf.assert_plan_compatible(workflow, plan, mode)

        if not is_resumable(workflow):
            raise WorkflowNotResumable(
                f"workflow {run_id} is {workflow.status!r}; a finished cycle is "
                f"not resumed automatically because re-running it would redo "
                f"completed work and re-propose actions"
            )

        # Engine provenance decides WHICH execution path is correct. NULL is
        # historical: such rows predate the column and keep the legacy recovery
        # behaviour they had before it existed. An unrecognised value is
        # refused -- guessing could execute the wrong graph or skip steps.
        engine = workflow.execution_engine
        if engine is not None and engine not in KNOWN_EXECUTION_ENGINES:
            raise WorkflowNotResumable(
                f"workflow {run_id} records unknown execution engine {engine!r}; "
                f"refusing to guess which executor should resume it"
            )

        # Ownership BEFORE any state change, so a live worker is protected.
        # ``stale_after_seconds`` permits taking over a DEAD-but-unexpired
        # lease without waiting out its full duration -- while still refusing a
        # worker whose heartbeat is current.
        generation = wf.claim(
            workflow,
            owner=f"resume:{uuid.uuid4().hex[:12]}",
            lease_seconds=lease_seconds,
            stale_after_seconds=stale_after_seconds,
        )

        # Only now is it safe to close out orphaned running steps: we hold the
        # lease, so nothing healthy can still be in flight.
        interrupted = wf.mark_interrupted_steps(
            workflow.id, reason="interrupted_by_prior_process_exit"
        )
        if interrupted:
            log.warning(
                "Workflow %s: marked %d step(s) interrupted: %s",
                run_id, len(interrupted), interrupted,
            )

        if engine == EXECUTION_ENGINE_LANGGRAPH:
            return self._execute_langgraph(
                merchant_id=merchant_id,
                mode=mode,
                orchestrator_run_id=run_id,
                params=params,
                workflow_id=workflow.id,
                wf=wf,
                resumed=True,
                generation=generation,
            )

        # ``legacy`` and historical NULL both continue through the legacy loop.
        return self._execute(
            merchant_id=merchant_id,
            mode=mode,
            plan=plan,
            orchestrator_run_id=run_id,
            params=params,
            workflow_id=workflow.id,
            wf=wf,
            resumed=True,
            generation=generation,
        )

    # ── shared execution ────────────────────────────────────────────────

    def _execute(
        self,
        *,
        merchant_id: uuid.UUID,
        mode: str,
        plan: Any,
        orchestrator_run_id: str,
        params: dict[str, Any] | None,
        workflow_id: uuid.UUID,
        wf: WorkflowRunService,
        resumed: bool,
        generation: int,
    ) -> OrchestrationSummary:
        """
        The legacy step-by-step execution path.

        Shared by ``run(use_langgraph=False)`` and by recovery of a cycle whose
        recorded engine is ``legacy`` (or NULL, for rows that predate engine
        provenance). The LangGraph path has its own executor, but both use the
        same durable step identity and reuse policy, so a resumed cycle cannot
        drift from a fresh one on the same engine.
        """
        ctx = AgentContext(
            db=self.db,
            merchant_id=merchant_id,
            mode=mode,
            params=params or {},
            llm=self.llm,
            embedding_provider=self.embedding_provider,
        )
        summary = OrchestrationSummary(
            orchestrator_run_id=orchestrator_run_id,
            merchant_id=str(merchant_id),
            mode=mode,
            resumed=resumed,
            workflow_id=str(workflow_id),
        )

        from backend.app.services.rag_context import RAGContextService

        ctx.shared["rag_context"] = RAGContextService(self.db).build(
            merchant_id,
            str((params or {}).get("objective") or "growth opportunity analysis"),
            window_days=int((params or {}).get("window_days", 30)),
        )
        # Commit the prologue BEFORE the plan starts. Building RAG context
        # leaves pending writes, and holding them across every step is what kept
        # a write lock open for the whole cycle -- which on a single-writer
        # database such as SQLite blocks the dedicated execution-state session
        # below. The prologue is context setup, never an agent's partial
        # writes, so committing it here is safe.
        try:
            self.db.commit()
        except Exception:
            log.exception("Failed to commit the orchestration prologue")
            try:
                self.db.rollback()
            except Exception:
                pass

        # Reuse is an EVIDENCE decision per step, not a status whitelist. A
        # partially completed step is only replayed when the persisted evidence
        # shows that is safe for downstream steps; otherwise it is retried or
        # held for reconciliation.
        attempts = wf.attempt_rows(workflow_id)
        already_done: dict[str, Any] = {}
        needs_reconciliation: list[str] = []
        for key, row in attempts.items():
            decision = wf.decide(step_row=row, merchant_id=merchant_id)
            if decision.verdict is ReuseVerdict.REUSE:
                already_done[key] = row
            elif decision.verdict is ReuseVerdict.RECONCILE:
                # Never reused and never blindly retried: an external effect may
                # have occurred without a recorded outcome.
                needs_reconciliation.append(key)
        if needs_reconciliation:
            log.warning(
                "Workflow %s: %d step(s) held for reconciliation, not reused and "
                "not retried: %s",
                orchestrator_run_id, len(needs_reconciliation),
                needs_reconciliation,
            )
        summary.needs_reconciliation = list(needs_reconciliation)

        for step_index, (agent_name, step_params) in enumerate(plan):
            # ── heartbeat ──────────────────────────────────────────────
            try:
                wf_row = self.db.get(AgentWorkflowRun, workflow_id)
                if wf_row is not None:
                    wf.heartbeat(wf_row, expected_generation=generation)
                    self.db.commit()
            except Exception:
                pass

            # ── cancellation checkpoint ────────────────────────────────
            # Checked BEFORE the step's records are written and before the
            # agent body runs, so a cancelled cycle starts no further work.
            #
            # This is cooperative between steps, not pre-emptive. If a step is
            # already inside an agent body, or inside an external call the
            # provider controls, that work cannot be recalled -- which is why
            # the cancel endpoint also marks the cycle cancelled immediately,
            # so no surface keeps showing it as live while it winds down.
            if is_cancel_requested(self.db, workflow_id):
                log.info(
                    "Workflow %s: cancellation observed before step %d (%s); "
                    "no further steps will start",
                    orchestrator_run_id, step_index, agent_name,
                )
                summary.status = "cancelled"
                summary.cancelled_at_step = step_index
                self._finalise_cancelled(
                    wf=wf, workflow_id=workflow_id, merchant_id=merchant_id,
                    run_id=orchestrator_run_id, generation=generation,
                )
                return summary

            agent = AGENT_INSTANCES.get(agent_name)
            if agent is None:
                continue
            step_key = step_key_for(
                mode, step_index, agent_name, step_params.get("phase")
            )
            if step_key in needs_reconciliation:
                # Recorded as skipped so the gap is visible in the plan and in
                # the audit trail rather than silently vanishing.
                wf.mark_needs_reconciliation(workflow_id, step_key)
                summary.agents_run.append(
                    self._reconciliation_entry(agent_name, step_key)
                )
                continue
            summary.resumed_steps.append(
                {
                    "step_index": step_index,
                    "step_key": step_key,
                    "agent": agent_name,
                    "phase": step_params.get("phase"),
                }
            )

            # ── reuse rather than re-run ────────────────────────────
            prior = already_done.get(step_key)
            if prior is not None:
                summary.agents_run.append(self._reuse_step(prior))
                self._replay_step_into_shared_ctx(
                    agent_name, prior, step_params, ctx.shared
                )
                # A reused step is still a step whose output the caller needs.
                self._capture_action_plan(
                    agent_name, dict(prior.output_summary or {}), summary
                )
                continue

            step_ctx_params = dict(ctx.params)
            step_ctx_params.update(step_params)
            step_ctx_params["orchestrator_run_id"] = orchestrator_run_id
            step_ctx_params["_rag_context"] = ctx.shared.get("rag_context", {})
            # Scopes a specialist's Phase 4 proposal to this execution so a
            # retry proposes the same action rather than a new one.
            step_ctx_params["workflow_run_id"] = str(workflow_id)

            if mode == "growth_team":
                if "manager_debate_id" in ctx.shared:
                    step_ctx_params["debate_id"] = ctx.shared.get("manager_debate_id")
                if agent_name in {"MarketingAgent", "ProductAgent", "DesignerAgent", "SoftwareAgent"}:
                    if "manager_delegations" in ctx.shared:
                        from backend.app.models.enums import DebateStatus
                        from backend.app.services.agent_debate_service import AgentDebateService

                        AgentDebateService(self.db).update_debate_status(
                            uuid.UUID(str(ctx.shared["manager_debate_id"])),
                            DebateStatus.debating,
                        )
                        for delegation in ctx.shared["manager_delegations"]:
                            if delegation["assigned_to"].lower() == agent_name.lower().replace("agent", ""):
                                step_ctx_params["task_id"] = delegation["task_id"]
                                break

            step_ctx = AgentContext(
                db=self.db,
                merchant_id=merchant_id,
                mode=mode,
                params=step_ctx_params,
                llm=self.llm,
                embedding_provider=self.embedding_provider,
                shared=ctx.shared,
            )
            from backend.app.ai.langchain_adapter.adapter import LangChainAgentAdapter

            step_ctx.shared["langchain_adapter"] = LangChainAgentAdapter(
                agent_name=agent_name,
                db=self.db,
                merchant_id=merchant_id,
                llm=self.llm,
            )

            # ── durable "step started", on its own persistence boundary ──
            # A dedicated session on the same Engine, so this commit reaches
            # exactly the start row and never the merchant business writes in
            # self.db. The agent has not started yet, so nothing partial exists
            # either way; the boundary exists so a FUTURE unrelated pending
            # write cannot ride along.
            step_record_args = dict(
                merchant_id=merchant_id,
                agent_name=agent_name,
                orchestrator_run_id=orchestrator_run_id,
                mode=mode,
                input_summary={"params": _safe_params(step_ctx.params)},
                workflow_id=workflow_id,
                step_key=step_key,
                step_index=step_index,
                attempt=wf.next_attempt(workflow_id, step_key),
            )
            state = self._state_session()
            run_pk: uuid.UUID | None = None
            # Whether the dedicated session is usable. Always true on
            # PostgreSQL. On a single-writer database (SQLite) the main
            # session's lock can make it unusable, and then the record falls
            # back to the main session: degraded isolation, but never a missing
            # audit row -- the evidence recovery depends on.
            dedicated = True
            try:
                run_pk = wf.record_step_start(
                    state,
                    expected_generation=generation,
                    **step_record_args,
                )
            except StaleLeaseError:
                # This worker has been fenced out. Re-raise: continuing would let
                # an obsolete worker write into a cycle a newer owner now holds.
                log.error(
                    "Workflow %s: lease lost before starting %s; abandoning cycle",
                    orchestrator_run_id, agent_name,
                )
                state.close()
                raise
            except Exception:
                log.warning(
                    "Dedicated execution-state session unusable for %s; falling "
                    "back to the main session, which degrades the isolation "
                    "guarantee. This matters on single-writer databases.",
                    agent_name, exc_info=True,
                )
                try:
                    self.db.rollback()
                    run_pk = wf.record_step_start(
                        self.db, commit=False, **step_record_args
                    )
                    dedicated = False
                except Exception:
                    # Never fatal: losing the audit row must not lose the
                    # analysis. Logged loudly so the gap is visible.
                    log.exception("Failed to persist step start for %s", agent_name)
                    run_pk = None

            try:
                t0 = time.perf_counter()
                savepoint = self.db.begin_nested()
                try:
                    # Scope Phase 4 proposal idempotency to this cycle for every
                    # agent, including those that call create_action directly.
                    with current_workflow(workflow_id):
                        result: AgentResult = agent.execute(step_ctx)
                    if result.ok:
                        savepoint.commit()
                    else:
                        savepoint.rollback()
                except Exception as exc:  # belt & braces around the boundary
                    log.exception("Orchestrator caught escape from %s", agent_name)
                    savepoint.rollback()
                    result = AgentResult(agent_name=agent_name, status="failed")
                    result.errors.append(f"{type(exc).__name__}: {exc}")

                if mode == "growth_team" and result.ok and self.llm is not None:
                    self._ground_debate_messages(
                        ctx,
                        agent_name=agent_name,
                        phase=str(step_ctx_params.get("phase", "investigate")),
                        result=result,
                    )
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                result.total_ms = max(result.total_ms, elapsed_ms)

                # Outcome on the same dedicated session. Recorded AFTER the
                # savepoint resolved, so a step whose business writes were
                # rolled back still records why it failed.
                if run_pk is not None:
                    try:
                        if dedicated:
                            wf.record_step_result(
                                state, run_pk, result,
                                expected_generation=generation,
                                workflow_id=workflow_id,
                            )
                        else:
                            wf.record_step_result(
                                self.db, run_pk, result, commit=False,
                                expected_generation=generation,
                                workflow_id=workflow_id,
                            )
                    except StaleLeaseError:
                        # The outcome must NOT be recorded: this worker lost the
                        # cycle, and a newer owner decides what happens next.
                        log.error(
                            "Workflow %s: lease lost while finishing %s; "
                            "abandoning cycle",
                            orchestrator_run_id, agent_name,
                        )
                        raise
                    except Exception:  # observability must never break the flow
                        log.exception("Failed to persist AgentRun for %s", agent_name)
            finally:
                state.close()

            summary.agents_run.append(self._agent_entry(result))
            ctx.shared.setdefault("ranked_opportunities", [])
            if "ranked_opportunities" in result.output:
                ctx.shared["ranked_opportunities"] = result.output["ranked_opportunities"]

            if mode in ("growth_team", "team") and agent_name in MAIN_GROWTH_TEAM_AGENTS:
                self._share_findings(agent_name, result, ctx.shared)

            self._capture_action_plan(agent_name, result.output, summary)

            # Commit the step outcome in EVERY mode. fast/deep previously
            # committed only at the very end, so a crash lost the whole cycle.
            try:
                self.db.commit()
            except Exception:
                log.exception("Per-step commit failed for %s", agent_name)
                try:
                    self.db.rollback()
                except Exception:
                    pass

        summary.debate_id = (
            str(ctx.shared.get("manager_debate_id"))
            if ctx.shared.get("manager_debate_id")
            else None
        )
        summary.ranked_opportunities = list(ctx.shared.get("ranked_opportunities", []))
        summary.totals = {
            "opportunities_created": sum(a["opportunities_created"] for a in summary.agents_run),
            "actions_proposed": sum(a["actions_proposed"] for a in summary.agents_run),
            "signals_detected": sum(a["signals_detected"] for a in summary.agents_run),
            "insights_generated": sum(a["insights_generated"] for a in summary.agents_run),
            "experiments_proposed": sum(a["experiments_proposed"] for a in summary.agents_run),
            "failed_agents": sum(1 for a in summary.agents_run if a["status"] == "failed"),
            "reused_steps": sum(1 for a in summary.agents_run if a.get("reused")),
        }

        failed_agents = [a for a in summary.agents_run if a["status"] == "failed"]
        if failed_agents and len(failed_agents) == len(summary.agents_run):
            summary.status = "failed"
        elif failed_agents:
            summary.status = "partial_success"

        if mode in ("deep", "growth_team", "team"):
            self._remember_run(ctx, summary)

        # Terminal state, so the cycle is unambiguously finished and a later
        # resume is refused by policy rather than by accident.
        if needs_reconciliation:
            # An uncertain external effect outranks a computed pass/fail: the
            # cycle is not safe to call complete.
            summary.status = "needs_reconciliation"
        terminal = {
            "failed": "failed",
            "partial_success": "partial",
            "needs_reconciliation": "needs_reconciliation",
            "cancelled": "cancelled",
            "superseded": "interrupted",
        }.get(summary.status, "completed")
        try:
            workflow_row = wf.get_workflow(merchant_id=merchant_id, run_id=orchestrator_run_id)
            if workflow_row is not None:
                wf.finish_workflow(
                    workflow_row,
                    status=terminal,
                    expected_generation=generation,
                )
        except StaleLeaseError:
            # A newer owner already owns this cycle. Its state wins; this worker
            # must not overwrite it, and must say so rather than claim success.
            log.error(
                "Workflow %s: lease lost before finalisation; a newer owner now "
                "holds this cycle", orchestrator_run_id,
            )
            summary.status = "superseded"
            raise
        except Exception:
            log.exception("Failed to finalise workflow %s", orchestrator_run_id)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

        return summary

    # ── step reuse ──────────────────────────────────────────────────────

    @staticmethod
    def _capture_action_plan(agent_name: str, output: dict[str, Any], summary: Any) -> None:
        """Surface ManagerAgent's action plan on the returned summary.

        Used by BOTH the execute and reuse paths. Having only the execute path
        meant a resumed workflow whose Manager step was reused reported
        ``action_plan=None`` for work that had durably completed.
        """
        if agent_name == "ManagerAgent" and isinstance(output, dict):
            if "action_plan" in output:
                summary.action_plan = output["action_plan"]

    def _finalise_cancelled(
        self,
        *,
        wf: Any,
        workflow_id: uuid.UUID,
        merchant_id: uuid.UUID,
        run_id: str,
        generation: int,
    ) -> None:
        """
        Record a cancelled cycle as terminal, once.

        The cancel endpoint already flipped the status; this is the worker's own
        confirmation, and it must tolerate losing that race (the endpoint may
        have bumped ``lease_generation`` out from under us). Tolerating it is
        what stops a cancelled cycle from raising a fencing error and looking
        like a crash to the operator who deliberately stopped it.
        """
        from backend.app.models.enums import WorkflowStatus
        from backend.app.services.workflow_run_service import StaleLeaseError

        row = wf.get_workflow(merchant_id=merchant_id, run_id=run_id)
        if row is None:
            return
        if row.status in (
            WorkflowStatus.cancelled.value,
            WorkflowStatus.interrupted.value,
        ):
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
            return
        try:
            wf.finish_workflow(
                row, status=WorkflowStatus.cancelled.value,
                expected_generation=generation,
            )
            self.db.commit()
        except StaleLeaseError:
            # The cancel endpoint got there first. That is the happy path.
            self.db.rollback()
        except Exception:
            log.exception("Failed to finalise cancelled workflow %s", run_id)
            try:
                self.db.rollback()
            except Exception:
                pass

    @staticmethod
    def _reconciliation_entry(agent_name: str, step_key: str) -> dict[str, Any]:
        """
        Summary entry for a step held back for reconciliation.

        Deliberately NOT shaped like a success: zero counts, an explicit status,
        and the reason inline, so no consumer can mistake it for work that
        produced a result.
        """
        return {
            "agent": agent_name,
            "status": "needs_reconciliation",
            "opportunities_created": 0,
            "actions_proposed": 0,
            "insights_generated": 0,
            "signals_detected": 0,
            "experiments_proposed": 0,
            "memories_written": 0,
            "tools_used": [],
            "errors": [
                "step held for reconciliation: an external effect may be in "
                f"flight (step_key={step_key})"
            ],
            "latency_ms": {"total": 0, "llm": 0, "db": 0, "tool": 0},
            "output": {},
            "reused": False,
            "needs_reconciliation": True,
        }

    @staticmethod
    def _reuse_step(run_row: Any) -> dict[str, Any]:
        """
        Rebuild a summary entry from a persisted step instead of re-running it.

        Marked ``reused: True`` so a caller can tell replayed work from
        freshly executed work and never report a replay as new activity.
        """
        return {
            "agent": run_row.agent_name,
            "status": str(getattr(run_row.status, "value", run_row.status)),
            "opportunities_created": run_row.opportunities_created or 0,
            "actions_proposed": run_row.actions_proposed or 0,
            "insights_generated": run_row.insights_generated or 0,
            "signals_detected": run_row.signals_detected or 0,
            "experiments_proposed": run_row.experiments_proposed or 0,
            "memories_written": 0,
            "tools_used": list(run_row.tools_used or []),
            "errors": list(run_row.errors or []),
            "latency_ms": {
                "total": run_row.total_latency_ms or 0,
                "llm": run_row.llm_latency_ms or 0,
                "db": run_row.db_latency_ms or 0,
                "tool": run_row.tool_latency_ms or 0,
            },
            "output": _safe_output(dict(run_row.output_summary or {})),
            "reused": True,
        }

    @staticmethod
    def _replay_step_into_shared_ctx(
        agent_name: str,
        run_row: Any,
        step_params: dict[str, Any],
        shared: dict[str, Any],
    ) -> None:
        """
        Restore a reused step's contribution to the cross-agent scratchpad.

        Without this a resumed run would lose exactly the findings that later
        steps depend on, silently degrading the final synthesis.
        """
        output = dict(run_row.output_summary or {})
        shared.setdefault("ranked_opportunities", [])
        if "ranked_opportunities" in output:
            shared["ranked_opportunities"] = output["ranked_opportunities"]
        # Same function the live path uses. Calling _share_findings here would
        # bind (agent_name, output, shared) to (self, agent_name, result,
        # shared) -- dropping self and omitting shared, raising TypeError.
        _publish_findings(agent_name, output, shared)

    def _ground_debate_messages(
        self,
        ctx: AgentContext,
        *,
        agent_name: str,
        phase: str,
        result: AgentResult,
    ) -> None:
        """Replace deterministic timeline copy with an LLM-grounded turn."""
        from backend.app.models.agent_debate import AgentMessage

        debate_id = ctx.shared.get("manager_debate_id")
        if not debate_id:
            return

        messages = list(
            self.db.query(AgentMessage)
            .filter(AgentMessage.debate_id == uuid.UUID(str(debate_id)))
            .order_by(AgentMessage.created_at.desc())
            .limit(4)
            .all()
        )
        if not messages:
            return

        evidence = {
            "merchant_context": ctx.shared.get("rag_context", {}),
            "agent_output": result.output,
            "recent_debate": [
                {"agent": message.from_agent, "type": message.message_type, "content": message.content}
                for message in reversed(messages)
            ],
        }
        prompt = json.dumps(
            {
                "agent": agent_name,
                "phase": phase,
                "instruction": (
                    "Write the next live debate turn for the named specialist. Use only verified merchant "
                    "context and the agent output. Address the recent debate when useful. Do not invent or "
                    "round any numbers. Return 2-4 concise plain-English sentences."
                ),
                "evidence": evidence,
            },
            default=str,
        )
        generated = self.llm.generate(
            "You are a specialist agent in a multi-agent growth debate. Every claim must be grounded in the supplied real merchant data.",
            prompt,
            temperature=0.35,
            max_tokens=220,
        ).strip()
        if generated:
            messages[0].content = generated

    def _share_findings(self, agent_name: str, result: AgentResult, shared: dict[str, Any]) -> None:
        """Share findings between main growth team agents via shared context.

        Signature retained for every existing call site; the mapping itself now
        lives in ``_publish_findings`` so that replaying a persisted step uses
        exactly the same rules as running it live.
        """
        _publish_findings(agent_name, result.output or {}, shared)

    # ── helpers ──────────────────────────────────────────────────────────

    def _remember_run(self, ctx: AgentContext, summary: OrchestrationSummary) -> None:
        try:
            memory_agent = AGENT_INSTANCES.get("GrowthMemoryAgent")
            if memory_agent is None or not summary.totals.get("actions_proposed"):
                return
            persist_ctx = AgentContext(
                db=self.db,
                merchant_id=ctx.merchant_id,
                mode=ctx.mode,
                params={
                    **ctx.params,
                    "phase": "persist",
                    "summary": (
                        f"Orchestrator run {summary.orchestrator_run_id}: "
                        f"{summary.totals['opportunities_created']} opportunities, "
                        f"{summary.totals['actions_proposed']} actions proposed "
                        f"(awaiting human approval)."
                    ),
                    "importance": 0.6,
                    "orchestrator_run_id": summary.orchestrator_run_id,
                },
                shared=ctx.shared,
            )
            memory_agent.execute(persist_ctx)
        except Exception:  # pragma: no cover — memory must never crash runs
            log.exception("Final memory write failed")

    @staticmethod
    def _agent_entry(result: AgentResult) -> dict[str, Any]:
        return {
            "agent": result.agent_name,
            "status": result.status,
            "opportunities_created": result.opportunities_created,
            "actions_proposed": result.actions_proposed,
            "insights_generated": result.insights_generated,
            "signals_detected": result.signals_detected,
            "experiments_proposed": result.experiments_proposed,
            "memories_written": result.memories_written,
            "tools_used": result.tools_used,
            "errors": result.errors,
            "latency_ms": {
                "total": result.total_ms,
                "llm": result.llm_ms,
                "db": result.db_ms,
                "tool": result.tool_ms,
            },
            "output": _safe_output(result.output),
        }


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Strip anything secret-shaped before persisting an input summary."""
    safe = {}
    for key, value in params.items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "secret", "token", "password")):
            continue
        safe[key] = value if isinstance(value, (str, int, float, bool)) else str(value)[:200]
    return safe


def _safe_output(output: dict[str, Any]) -> dict[str, Any]:
    """Output summaries are JSON-safe structured dicts (no raw prompts)."""
    try:
        import json

        json.dumps(output, default=str)
        return output
    except Exception:
        return {"note": "output contained non-serializable values; omitted"}


#: Which shared-context slot each specialist's findings belong to.
FINDINGS_SLOT = {
    "MarketingAgent": "marketing_findings",
    "ProductAgent": "product_findings",
    "DesignerAgent": "designer_findings",
    "SoftwareAgent": "software_findings",
}


def _publish_findings(agent_name: str, output: dict[str, Any], shared: dict[str, Any]) -> None:
    """
    Publish one agent's findings into the cross-agent scratchpad.

    Takes the OUTPUT DICT, not an AgentResult, so the live execution path and
    the replay-from-persistence path cannot drift apart: a resumed step holds
    only what was written to the database, never a live result object.

    Idempotent -- replaying the same step twice writes the same slots twice with
    the same values, so a duplicated resume cannot corrupt the scratchpad.
    """
    if not isinstance(output, dict):
        return
    slot = FINDINGS_SLOT.get(agent_name)
    if slot is not None:
        shared[slot] = output
    # ManagerAgent carries the debate coordinates that later specialist steps
    # read via ctx.shared, so a reused Manager step must restore them too.
    if agent_name == "ManagerAgent":
        if "debate_id" in output:
            shared["manager_debate_id"] = output["debate_id"]
        if "delegations" in output:
            shared["manager_delegations"] = output["delegations"]


def _as_utc(value: datetime) -> datetime:
    """Naive timestamps from SQLite are UTC; normalise before comparing."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _plan_for(mode: str) -> Any:
    """The plan tuple for a mode. Single place mode -> plan is decided."""
    return {
        "fast": FAST_PLAN,
        "deep": DEEP_PLAN,
        "team": AI_TEAM_PLAN,
        "growth_team": GROWTH_TEAM_PLAN,
    }[mode]
