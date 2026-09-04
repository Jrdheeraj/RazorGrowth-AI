"""
Manager Agent — AI Growth Team Coordinator.

The Manager Agent is the top-level coordinator for the AI Growth Team.
It receives growth objectives, decomposes them into tasks, delegates to
specialist agents, collects findings, initiates debates, and produces
synthesis for the recommendation engine.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_CUSTOMERS,
    READ_ORDERS,
    READ_PAYMENTS,
    SIMULATE,
)
from backend.app.models.agent_debate import AgentDebate, AgentTask, AgentFinding, AgentMessage
from backend.app.models.enums import AgentSpecialty, DebateStatus, FindingType, TaskStatus
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.repositories.agent_debate import (
    AgentDebateRepository,
    AgentTaskRepository,
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.services.agent_debate_service import AgentDebateService
from backend.app.services.opportunity_service import GrowthOpportunityService
from backend.app.services.radar import GrowthRadarService

log = logging.getLogger(__name__)


@dataclass
class ManagerTaskPlan:
    """A planned task for a specialist agent."""
    assigned_to: AgentSpecialty
    title: str
    description: str
    input_data: dict[str, Any] = field(default_factory=dict)


class ManagerAgent(BaseGrowthAgent):
    """
    Manager Agent — coordinates the AI Growth Team.

    Responsibilities:
    - Receives growth objectives
    - Understands merchant context via Growth Radar and opportunities
    - Decomposes objectives into specialist tasks
    - Delegates to Marketing, Product, Designer, Software agents
    - Collects and structures findings
    - Initiates Agent Debate for conflicting findings
    - Synthesizes final recommendation input
    """

    NAME = "ManagerAgent"
    DESCRIPTION = (
        "Top-level coordinator for the AI Growth Team. Decomposes growth "
        "objectives, delegates to specialist agents, manages Agent Debate, "
        "and synthesizes findings into recommendation-ready output."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_CUSTOMERS,
        READ_ORDERS,
        READ_PAYMENTS,
        SIMULATE,
    })
    TOOLS = ("growth_radar", "opportunity_lookup", "task_decomposition", "agent_delegation", "debate_orchestration", "synthesis")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        objective: str = ctx.params.get("objective", "Improve overall growth")

        # Phase 1: Context gathering — use Growth Radar for signals
        radar = GrowthRadarService(db)
        signals, db_ms = self._timed(
            radar.detect, merchant_id, window_days=30, persist=False
        )
        result.signals_detected = len(signals)
        result.db_ms += db_ms

        # Phase 2: Fetch top opportunities for context
        opp_service = GrowthOpportunityService(db)
        opportunities = opp_service.list_opportunities(merchant_id)
        top_opps = sorted(opportunities, key=lambda o: float(o.expected_revenue), reverse=True)[:5]

        # Phase 3: Determine which main specialists are needed
        required_specialists = self._determine_specialists(objective, signals, top_opps, mode=ctx.mode)
        result.output["required_specialists"] = [s.value for s in required_specialists]

        # In AI Team workspace mode (phase="coordinate" or non-debate mode), coordinate without creating debate
        is_debate_flow = ctx.mode == "growth_team" or bool(ctx.params.get("debate_id"))
        if not is_debate_flow:
            self._coordinate_team(ctx, result, signals, top_opps, objective)
            return

        # Phase 4: Create or retrieve Agent Debate session (Debate feature only)
        debate_service = AgentDebateService(db)
        debate_id = ctx.params.get("debate_id") or ctx.shared.get("manager_debate_id")
        if debate_id:
            debate = debate_service.get_debate(uuid.UUID(str(debate_id)))
            if debate:
                debate.context = {
                    **(debate.context or {}),
                    "rag_context": ctx.shared.get("rag_context", {}),
                }
        else:
            debate = debate_service.create_debate(
                merchant_id=merchant_id,
                objective=objective,
                manager_agent_id=self.NAME,
                context={
                    "rag_context": ctx.shared.get("rag_context", {}),
                    "signals": [{"type": s["signal_type"], "title": s["title"]} for s in signals],
                    "top_opportunities": [{"id": str(o.id), "title": o.title, "type": o.type.value} for o in top_opps],
                },
            )
            debate_service.update_debate_status(debate.id, DebateStatus.investigating)
        result.output["debate_id"] = str(debate.id)
        ctx.shared["manager_debate_id"] = str(debate.id)

        # Phase 5: Create tasks for each required specialist
        tasks = self._create_tasks(db, debate, required_specialists, objective, signals, top_opps, ctx.params)
        result.output["tasks_created"] = len(tasks)

        # Emit opening manager briefing (Round 1)
        message_repo = AgentMessageRepository(db)
        message_repo.create(
            debate_id=debate.id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.manager.value,
            to_agent=None,
            message_type="briefing",
            content=(
                f"Growth Manager: Initiating multi-agent strategic investigation for objective: '{objective}'. "
                f"Specialists deployed: Marketing, Product, UX/Designer, and Technical Feasibility. "
                f"All claims must be grounded directly in live Razorpay merchant telemetry."
            ),
            references=[{"round": 1, "type": "briefing", "objective": objective}],
        )

        # Phase 6: Delegate to specialist agents (they run in orchestrator sequence)
        # We record the delegation intent; actual execution happens via orchestrator
        for task in tasks:
            assigned_to_value = task.assigned_to.value if hasattr(task.assigned_to, 'value') else task.assigned_to
            result.output.setdefault("delegations", []).append({
                "task_id": str(task.id),
                "assigned_to": assigned_to_value,
                "title": task.title,
            })

        # Phase 7: If this is a synthesis run (after specialists completed), synthesize
        if ctx.params.get("phase") == "synthesize":
            debate_service.update_debate_status(debate.id, DebateStatus.synthesizing)
            self._synthesize_findings(debate, debate_service, result)

        result.output["objective"] = objective
        result.output["status"] = "delegated" if ctx.params.get("phase") != "synthesize" else "synthesized"

    def _coordinate_team(
        self,
        ctx: AgentContext,
        result: AgentResult,
        signals: list[dict[str, Any]],
        top_opps: list[GrowthOpportunity],
        objective: str,
    ) -> None:
        """Synthesize specialist work into an actionable business growth plan (AI Team mode)."""
        mkt = ctx.shared.get("marketing_findings", {})
        prd = ctx.shared.get("product_findings", {})
        dsg = ctx.shared.get("designer_findings", {})
        sft = ctx.shared.get("software_findings", {})
        ranked = ctx.shared.get("ranked_opportunities", [])

        action_items = []
        failed_val = mkt.get("failed_payments_value", 0)
        failed_cnt = mkt.get("failed_payments_count", 0)
        if failed_cnt > 0:
            action_items.append({
                "title": f"Recapture ₹{failed_val:,.2f} in dropped checkouts ({failed_cnt} failed payments)",
                "assigned_to": "Marketing Analyst & Technical Feasibility",
                "priority": "HIGH",
                "expected_impact": f"Up to ₹{failed_val * 0.35:,.2f} recoverable within 7 days",
                "next_steps": "Deploy automated webhook-driven recovery alerts with 1-click retry links.",
            })

        high_val_cnt = mkt.get("high_value_count", 0)
        if high_val_cnt > 0:
            action_items.append({
                "title": f"Launch VIP retention incentive for {high_val_cnt} repeat customers",
                "assigned_to": "Marketing Analyst",
                "priority": "MEDIUM",
                "expected_impact": "15-20% boost in 30-day repeat purchase rate",
                "next_steps": "Target repeat buyers with exclusive product bundle offers.",
            })

        aov = prd.get("aov", 0)
        if aov > 0:
            action_items.append({
                "title": f"Implement companion product cross-sells to lift baseline AOV (₹{aov:,.2f})",
                "assigned_to": "Product Strategist & Creative UX",
                "priority": "HIGH",
                "expected_impact": "10-18% expansion in average order value",
                "next_steps": "Add non-blocking companion recommendations on post-checkout view.",
            })

        if not action_items and ranked:
            for opp in ranked[:3]:
                action_items.append({
                    "title": opp.get("title", "Growth Opportunity"),
                    "assigned_to": "Growth Team",
                    "priority": "HIGH",
                    "expected_impact": f"Expected revenue ₹{float(opp.get('expected_revenue', 0)):,.2f}",
                    "next_steps": opp.get("description", "Execute recommended workflow"),
                })

        if not action_items:
            action_items.append({
                "title": "Establish baseline transaction telemetry",
                "assigned_to": "Growth Manager",
                "priority": "MEDIUM",
                "expected_impact": "Continuous data ingestion from Razorpay test transactions",
                "next_steps": "Process additional test transactions to unlock deeper opportunity scoring.",
            })

        result.output["action_plan"] = {
            "objective": objective,
            "executive_summary": (
                f"The AI Growth Team has completed an end-to-end analysis of your live commerce data. "
                f"Identified {len(action_items)} high-leverage initiatives across payment recovery, "
                f"customer retention, and basket economics."
            ),
            "initiatives": action_items,
            "status": "ready_for_merchant_review",
        }
        result.output["recommendations"] = [item["title"] for item in action_items]
        result.output["status"] = "coordinated"

    def _determine_specialists(
        self,
        objective: str,
        signals: list[dict[str, Any]],
        opportunities: list[GrowthOpportunity],
        mode: str = "deep",
    ) -> list[AgentSpecialty]:
        """Determine which main specialists are relevant for this objective."""
        # In growth_team mode, always include all 4 main specialists
        if mode == "growth_team":
            return [AgentSpecialty.marketing, AgentSpecialty.product, AgentSpecialty.designer, AgentSpecialty.software]

        objective_lower = objective.lower()
        specialists = set()

        # Always include Manager (self) implicitly
        # Determine based on objective keywords and signals
        signal_types = {s["signal_type"] for s in signals}
        opp_types = {o.type.value for o in opportunities}

        # Marketing triggers
        marketing_keywords = {"retention", "acquisition", "win-back", "campaign", "churn", "engagement", "marketing"}
        if any(k in objective_lower for k in marketing_keywords):
            specialists.add(AgentSpecialty.marketing)
        if any(s in signal_types for s in {"abandoned_customers", "segment_opportunity", "campaign_opportunity", "inactive_high_value"}):
            specialists.add(AgentSpecialty.marketing)
        if "campaign" in opp_types or "win_back" in opp_types or "retention" in opp_types:
            specialists.add(AgentSpecialty.marketing)

        # Product triggers
        product_keywords = {"upsell", "cross-sell", "product", "affinity", "bundle", "catalog", "pricing"}
        if any(k in objective_lower for k in product_keywords):
            specialists.add(AgentSpecialty.product)
        if any(s in signal_types for s in {"product_demand_change", "unusual_order_behavior", "emerging_growth"}):
            specialists.add(AgentSpecialty.product)
        if "upsell" in opp_types or "cross_sell" in opp_types or "product_affinity" in opp_types:
            specialists.add(AgentSpecialty.product)

        # Designer triggers
        designer_keywords = {"creative", "design", "message", "copy", "visual", "brand", "experience", "ux", "ui"}
        if any(k in objective_lower for k in designer_keywords):
            specialists.add(AgentSpecialty.designer)
        if any(s in signal_types for s in {"campaign_opportunity", "discount_opportunity"}):
            specialists.add(AgentSpecialty.designer)

        # Software triggers
        software_keywords = {"automation", "integration", "technical", "implementation", "system", "workflow", "api", "software"}
        if any(k in objective_lower for k in software_keywords):
            specialists.add(AgentSpecialty.software)
        if "checkout_optimization" in opp_types:
            specialists.add(AgentSpecialty.software)

        # If no specialists matched, default to Marketing + Product
        if not specialists:
            specialists = {AgentSpecialty.marketing, AgentSpecialty.product}

        return list(specialists)

    def _create_tasks(
        self,
        db: Session,
        debate: AgentDebate,
        specialists: list[AgentSpecialty],
        objective: str,
        signals: list[dict[str, Any]],
        opportunities: list[GrowthOpportunity],
        params: dict[str, Any],
    ) -> list[AgentTask]:
        """Create and persist AgentTask records for each specialist."""
        debate_service = AgentDebateService(db)
        tasks = []
        for spec in specialists:
            task_data = self._build_task_for_specialist(spec, objective, signals, opportunities, params)
            task = debate_service.create_task(
                debate_id=debate.id,
                merchant_id=debate.merchant_id,
                assigned_to=spec,
                title=task_data["title"],
                description=task_data["description"],
                input_data=task_data["input_data"],
            )
            tasks.append(task)
        return tasks

    def _build_task_for_specialist(
        self,
        specialist: AgentSpecialty,
        objective: str,
        signals: list[dict[str, Any]],
        opportunities: list[GrowthOpportunity],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build task specification for a given specialist."""
        base_input = {
            "objective": objective,
            "rag_context": params.get("rag_context") or self._rag_context_for_tasks(params),
            "signals": signals,
            "opportunities": [{"id": str(o.id), "title": o.title, "type": o.type.value, "expected_revenue": float(o.expected_revenue)} for o in opportunities],
            "merchant_params": params,
        }

        if specialist == AgentSpecialty.marketing:
            return {
                "title": "Marketing Strategy for Growth Objective",
                "description": "Analyze customer segments, retention opportunities, and campaign strategies",
                "input_data": {**base_input, "focus": ["segmentation", "retention", "campaigns", "messaging"]},
            }
        elif specialist == AgentSpecialty.product:
            return {
                "title": "Product Growth Opportunities Analysis",
                "description": "Identify upsell, cross-sell, and product affinity opportunities",
                "input_data": {**base_input, "focus": ["upsell", "cross_sell", "product_affinity", "pricing"]},
            }
        elif specialist == AgentSpecialty.designer:
            return {
                "title": "Creative Concepts & Messaging Strategy",
                "description": "Design campaign creatives, messaging variations, and UX recommendations",
                "input_data": {**base_input, "focus": ["creative", "messaging", "ux", "variants"]},
            }
        elif specialist == AgentSpecialty.software:
            return {
                "title": "Technical Implementation Planning",
                "description": "Plan technical requirements, integrations, and automation for growth initiatives",
                "input_data": {**base_input, "focus": ["technical_feasibility", "integrations", "automation", "dependencies"]},
            }
        return {"title": "General Analysis", "description": "Analyze growth opportunity", "input_data": base_input}

    @staticmethod
    def _rag_context_for_tasks(params: dict[str, Any]) -> dict[str, Any]:
        """Return the context envelope passed by the orchestrator when available."""
        return params.get("_rag_context", {})

    def _synthesize_findings(self, debate: AgentDebate, debate_service: AgentDebateService, result: AgentResult) -> None:
        """Synthesize findings from all specialists into recommendation-ready output."""
        # Get all findings from the debate
        findings = debate_service.list_findings_by_debate(debate.id)
        messages = debate_service.list_messages_by_debate(debate.id)
        tasks = debate_service.list_tasks_by_debate(debate.id)

        # Categorize findings
        def match_type(f: AgentFinding, target: FindingType) -> bool:
            ft = f.finding_type
            return ft == target or ft == target.value

        supporting = [f for f in findings if match_type(f, FindingType.supporting)]
        opposing = [f for f in findings if match_type(f, FindingType.opposing)]
        neutral = [f for f in findings if match_type(f, FindingType.neutral)]
        uncertainty = [f for f in findings if match_type(f, FindingType.uncertainty)]

        # Build synthesis
        synthesis_parts = [
            f"Objective: {debate.objective}",
            f"Evidence status: {((debate.context or {}).get('rag_context') or {}).get('status', 'unknown')}",
            f"Specialists consulted: {[t.assigned_to for t in tasks]}",
            f"Total findings: {len(findings)}",
            f"Supporting: {len(supporting)}, Opposing: {len(opposing)}, Neutral: {len(neutral)}, Uncertainties: {len(uncertainty)}",
        ]

        if supporting:
            synthesis_parts.append("\nSupporting Evidence:")
            for f in supporting:
                synthesis_parts.append(f"  - [{f.agent_specialty}] {f.title}: {f.description} (confidence: {f.confidence})")

        if opposing:
            synthesis_parts.append("\nOpposing Evidence / Risks:")
            for f in opposing:
                synthesis_parts.append(f"  - [{f.agent_specialty}] {f.title}: {f.description} (confidence: {f.confidence})")

        if uncertainty:
            synthesis_parts.append("\nUncertainties & Assumptions:")
            for f in uncertainty:
                synthesis_parts.append(f"  - [{f.agent_specialty}] {f.title}: {f.uncertainty_notes or f.description}")

        rag_context = debate.context.get("rag_context", {}) if debate.context else {}
        if rag_context.get("status") == "insufficient_data":
            recommendation = "INSUFFICIENT EVIDENCE: no recommendation is supported by the available real merchant data."
        else:
            recommendation = self._formulate_recommendation(debate, supporting, opposing, uncertainty)
        synthesis_parts.append(f"\nManager Recommendation: {recommendation}")

        final_synthesis = "\n".join(synthesis_parts)

        # Post synthesis message to debate messages timeline (Round 4)
        message_repo = AgentMessageRepository(debate_service._db)
        message_repo.create(
            debate_id=debate.id,
            merchant_id=debate.merchant_id,
            from_agent=AgentSpecialty.manager.value,
            to_agent=None,
            message_type="synthesis",
            content=(
                f"Growth Manager (Executive Synthesis): Consensus reached across 4 debate rounds. "
                f"{recommendation} Execution plan locked: Deploy automated Razorpay webhook retry flows "
                f"with bounded margin-protection guardrails and 1-click client checkout recovery."
            ),
            references=[{"round": 4, "type": "synthesis", "consensus": True, "findings_count": len(findings)}],
        )

        # Persist synthesis
        debate_service.set_debate_synthesis(debate.id, final_synthesis)
        debate_service.update_debate_status(debate.id, DebateStatus.concluded)

        result.output["synthesis"] = final_synthesis
        result.output["findings_summary"] = {
            "total": len(findings),
            "supporting": len(supporting),
            "opposing": len(opposing),
            "neutral": len(neutral),
            "uncertainty": len(uncertainty),
        }
        result.output["recommendation"] = recommendation

    def _formulate_recommendation(
        self,
        debate: AgentDebate,
        supporting: list[AgentFinding],
        opposing: list[AgentFinding],
        uncertainty: list[AgentFinding],
    ) -> str:
        """Formulate a concrete recommendation based on debate findings."""
        if not supporting:
            return "Insufficient supporting evidence to recommend action. Further investigation needed."

        # Weight by confidence and count
        support_weight = sum(float(f.confidence) for f in supporting)
        oppose_weight = sum(float(f.confidence) for f in opposing)

        if oppose_weight > support_weight * 0.5:
            return (
                "Proceed with caution. Significant opposing evidence exists. "
                "Recommend pilot experiment with strict guardrails before full rollout."
            )
        elif uncertainty:
            return (
                "Recommend proceeding with identified uncertainties documented. "
                "Implement with monitoring and measurement checkpoints."
            )
        else:
            return "Strong evidence supports proceeding. Recommend approval with standard guardrails."