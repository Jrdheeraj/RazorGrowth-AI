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
from typing import Any

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.registry import AGENT_INSTANCES, MAIN_GROWTH_TEAM_AGENTS
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
        if mode not in ("fast", "deep", "growth_team", "team"):
            raise ValueError("mode must be 'fast', 'deep', 'growth_team', or 'team'")
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

        from backend.app.services.rag_context import RAGContextService

        ctx.shared["rag_context"] = RAGContextService(self.db).build(
            merchant_id,
            str((params or {}).get("objective") or "growth opportunity analysis"),
            window_days=int((params or {}).get("window_days", 30)),
        )

        if mode == "fast":
            plan = FAST_PLAN
        elif mode == "deep":
            plan = DEEP_PLAN
        elif mode == "team":
            plan = AI_TEAM_PLAN
        else:  # growth_team
            plan = GROWTH_TEAM_PLAN

        for agent_name, step_params in plan:
            agent = AGENT_INSTANCES.get(agent_name)
            if agent is None:
                continue
            step_ctx_params = dict(ctx.params)
            step_ctx_params.update(step_params)
            step_ctx_params["orchestrator_run_id"] = orchestrator_run_id
            step_ctx_params["_rag_context"] = ctx.shared.get("rag_context", {})

            # For growth_team mode, pass debate_id and task_id from ManagerAgent to specialist agents
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
                        delegations = ctx.shared["manager_delegations"]
                        for delegation in delegations:
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

            if mode == "growth_team" and result.ok and self.llm is not None:
                self._ground_debate_messages(
                    ctx,
                    agent_name=agent_name,
                    phase=str(step_ctx_params.get("phase", "investigate")),
                    result=result,
                )
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

            # Share findings between main growth team agents (both in debate and team modes)
            if mode in ("growth_team", "team") and agent_name in MAIN_GROWTH_TEAM_AGENTS:
                self._share_findings(agent_name, result, ctx.shared)

            if agent_name == "ManagerAgent" and "action_plan" in result.output:
                summary.action_plan = result.output["action_plan"]

            if mode == "growth_team":
                self.db.commit()

        summary.debate_id = str(ctx.shared.get("manager_debate_id")) if ctx.shared.get("manager_debate_id") else None
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

        # Final memory write (deep, team, and growth_team modes) — remember what was decided
        if mode in ("deep", "growth_team", "team"):
            self._remember_run(ctx, summary)
        return summary

    def _ground_debate_messages(
        self,
        ctx: AgentContext,
        *,
        agent_name: str,
        phase: str,
        result: AgentResult,
    ) -> None:
        """Replace deterministic timeline copy with a Groq-grounded turn."""
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
        """Share findings between main growth team agents via shared context."""
        key_map = {
            "MarketingAgent": "marketing_findings",
            "ProductAgent": "product_findings",
            "DesignerAgent": "designer_findings",
            "SoftwareAgent": "software_findings",
        }
        if agent_name in key_map:
            shared[key_map[agent_name]] = result.output

        # Store ManagerAgent's debate_id and delegations for specialist agents
        if agent_name == "ManagerAgent":
            if "debate_id" in result.output:
                shared["manager_debate_id"] = result.output["debate_id"]
            if "delegations" in result.output:
                shared["manager_delegations"] = result.output["delegations"]

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
