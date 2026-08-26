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

The orchestrator NEVER approves, rejects, executes, or bypasses
guardrails. Its only bridge to execution is Phase 4's create_action()
which lands in 'requested' state.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.models.merchant import Merchant

log = logging.getLogger(__name__)

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


@dataclass
class OrchestrationSummary:
    orchestrator_run_id: str
    merchant_id: str
    mode: str
    status: str = "completed"
    agents_run: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    ranked_opportunities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "orchestrator_run_id": self.orchestrator_run_id,
            "merchant_id": self.merchant_id,
            "mode": self.mode,
            "status": self.status,
            "agents": self.agents_run,
            "totals": self.totals,
            "ranked_opportunities": self.ranked_opportunities,
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

    # ── public API ───────────────────────────────────────────────────────

    def run(
        self,
        merchant_id: uuid.UUID,
        *,
        mode: str = "deep",
        params: dict[str, Any] | None = None,
    ) -> OrchestrationSummary:
        if mode not in ("fast", "deep"):
            raise ValueError("mode must be 'fast' or 'deep'")
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise MerchantNotFoundError(f"Merchant {merchant_id} not found")

        orchestrator_run_id = uuid.uuid4().hex
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
        )

        plan = FAST_PLAN if mode == "fast" else DEEP_PLAN
        for agent_name, step_params in plan:
            agent = AGENT_INSTANCES.get(agent_name)
            if agent is None:
                continue
            step_ctx_params = dict(ctx.params)
            step_ctx_params.update(step_params)
            step_ctx_params["orchestrator_run_id"] = orchestrator_run_id
            step_ctx = AgentContext(
                db=self.db,
                merchant_id=merchant_id,
                mode=mode,
                params=step_ctx_params,
                llm=self.llm,
                embedding_provider=self.embedding_provider,
                shared=ctx.shared,
            )

            run_row = self.runs.start_run(
                merchant_id=merchant_id,
                agent_name=agent_name,
                orchestrator_run_id=orchestrator_run_id,
                mode=mode,
                input_summary={"params": _safe_params(step_ctx.params)},
            )

            t0 = time.perf_counter()
            savepoint = self.db.begin_nested()
            try:
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
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            result.total_ms = max(result.total_ms, elapsed_ms)

            try:
                self.runs.complete_run(run_row, result)
            except Exception:  # observability must never break the pipeline
                log.exception("Failed to persist AgentRun for %s", agent_name)

            summary.agents_run.append(self._agent_entry(result))
            ctx.shared.setdefault("ranked_opportunities", [])
            if "ranked_opportunities" in result.output:
                ctx.shared["ranked_opportunities"] = result.output["ranked_opportunities"]

        summary.ranked_opportunities = list(ctx.shared.get("ranked_opportunities", []))
        summary.totals = {
            "opportunities_created": sum(a["opportunities_created"] for a in summary.agents_run),
            "actions_proposed": sum(a["actions_proposed"] for a in summary.agents_run),
            "signals_detected": sum(a["signals_detected"] for a in summary.agents_run),
            "insights_generated": sum(a["insights_generated"] for a in summary.agents_run),
            "experiments_proposed": sum(a["experiments_proposed"] for a in summary.agents_run),
            "failed_agents": sum(1 for a in summary.agents_run if a["status"] == "failed"),
        }
        failed_agents = [
            a for a in summary.agents_run if a["status"] == "failed"
        ]
        if failed_agents and len(failed_agents) == len(summary.agents_run):
            summary.status = "failed"
        elif failed_agents:
            summary.status = "partial_success"

        # Final memory write (deep mode only) — remember what was decided
        if mode == "deep":
            self._remember_run(ctx, summary)
        return summary

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
