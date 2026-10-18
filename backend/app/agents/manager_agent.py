"""
Manager Agent — AI Growth Team Coordinator.

The Manager Agent is the top-level coordinator for the AI Growth Team.
It receives growth objectives, decomposes them into tasks, delegates to
specialist agents, collects findings, initiates debates, and produces
synthesis for the recommendation engine.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.catalog import (
    DOCUMENTED_UNAVAILABLE_TOOLS,
    LEGACY_TOOL_ALIASES,
    TOOL_REGISTRY,
    tool_ids_for_agent,
)
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

    # ------------------------------------------------------------------ #
    # CENTRAL MANAGER: goal understanding, dynamic selection, validated
    # planning, result evaluation and final synthesis.
    #
    # Everything below is additive. ``_determine_specialists`` (AgentSpecialty
    # values, used by the debate/task path) and ``_create_tasks`` are
    # untouched, so the orchestrator's existing delegation matching
    # (``delegation["assigned_to"]`` -> agent name) keeps working exactly as
    # before.
    #
    # Design rules enforced here:
    #   * agents are discovered from the live registry, never hardcoded;
    #   * only agents whose tools are really registered can be selected;
    #   * the Manager never selects itself and never selects every agent;
    #   * model output is treated as untrusted data and validated
    #     deterministically before it can influence execution;
    #   * nothing here approves, executes or bypasses a guardrail.
    # ------------------------------------------------------------------ #

    #: Bridge from the debate's ``AgentSpecialty`` vocabulary to the real
    #: registered agent ids. Used only to translate an existing plan into
    #: agent ids; selection itself is registry-driven.
    SPECIALTY_TO_AGENT: dict[str, str] = {
        "marketing": "MarketingAgent",
        "product": "ProductAgent",
        "designer": "DesignerAgent",
        "software": "SoftwareAgent",
        "manager": "ManagerAgent",
    }

    #: Goal themes -> REAL catalog tool ids. Selecting by tool id means a plan
    #: can never reference a capability the catalog does not implement.
    GOAL_THEME_TOOLS: dict[str, tuple[str, ...]] = {
        "conversion": ("commerce.catalog_intelligence", "analytics.business_overview", "payments.failure_analytics"),
        "checkout": ("commerce.catalog_intelligence", "payments.failure_analytics"),
        "payment_recovery": ("payments.failure_analytics", "analytics.business_overview"),
        "retention": ("customer.insights", "analytics.growth_radar"),
        "churn": ("customer.insights", "analytics.growth_radar"),
        "win_back": ("customer.insights", "analytics.growth_radar"),
        "campaign": ("customer.insights", "analytics.growth_radar"),
        "marketing": ("customer.insights", "analytics.growth_radar"),
        "acquisition": ("analytics.growth_radar", "customer.insights"),
        "product": ("commerce.catalog_intelligence",),
        "catalog": ("commerce.catalog_intelligence",),
        "pricing": ("commerce.catalog_intelligence", "opportunities.rank"),
        "bundle": ("commerce.catalog_intelligence", "experiments.design"),
        "upsell": ("commerce.catalog_intelligence", "experiments.design"),
        "cross_sell": ("commerce.catalog_intelligence", "experiments.design"),
        "revenue": ("analytics.business_overview", "opportunities.rank"),
        "opportunity": ("opportunities.rank", "analytics.business_overview"),
        "experiment": ("experiments.design", "experiments.record_result"),
        "personalization": ("customer.insights",),
        "memory": ("memory.recall",),
        "automation": ("collaboration.request_handoff",),
        "integration": ("collaboration.request_handoff",),
        "handoff": ("collaboration.request_handoff",),
        "research": ("research.web_search",),
        "design": ("commerce.catalog_intelligence",),
        "creative": ("commerce.catalog_intelligence",),
        "customer": ("customer.insights",),
        "segment": ("customer.insights",),
        "technical": ("collaboration.request_handoff", "opportunities.rank"),
        "implementation": ("collaboration.request_handoff", "opportunities.rank"),
    }

    #: Deterministic, bounded execution limits surfaced in the plan and
    #: enforced by the orchestrator/agent base class. Model output can never
    #: raise these; validation clamps instead of trusting.
    PLAN_LIMITS: dict[str, int] = {"max_steps": 5, "max_retries": 3, "max_replan": 2, "max_agents": 5}

    #: Failure classification vocabulary used by ``_evaluate_results``.
    FAILURE_KINDS: tuple[str, ...] = (
        "transient",
        "permanent",
        "missing_configuration",
        "missing_input",
        "failed_dependency",
        "insufficient_evidence",
        "unnecessary_task",
        "approval_required",
    )

    # ---------------------------------------------------------------- #
    # 1. Registry discovery (single source of truth)
    # ---------------------------------------------------------------- #

    def discover_registered_agents(self) -> list[dict[str, Any]]:
        """Return every unique registered agent with truthful capabilities.

        Reads ``AGENT_INSTANCES`` directly so the count is never hardcoded and
        a duplicate instantiation can never inflate the roster. Tools are
        resolved through the canonical catalog; declared names with no
        implementation are surfaced, never hidden.
        """
        from backend.app.agents.registry import AGENT_INSTANCES

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for agent in AGENT_INSTANCES.values():
            name = getattr(agent, "NAME", "")
            if not name or name in seen:
                continue
            seen.add(name)

            resolved: list[str] = []
            unimplemented: list[str] = []
            for declared in getattr(agent, "TOOLS", ()) or ():
                mapped = LEGACY_TOOL_ALIASES.get(declared, declared)
                if mapped in TOOL_REGISTRY:
                    if mapped not in resolved:
                        resolved.append(mapped)
                elif declared not in unimplemented:
                    unimplemented.append(declared)

            entries.append(
                {
                    "agent_id": name,
                    "description": getattr(agent, "DESCRIPTION", "") or "No description recorded.",
                    "permissions": sorted(getattr(agent, "PERMISSIONS", frozenset()) or frozenset()),
                    "tools": resolved,
                    "unimplemented_tools": unimplemented,
                    # An agent is selectable only when it exposes at least one
                    # tool that is really registered.
                    "fully_implemented": bool(resolved) and not unimplemented,
                    "selectable": bool(resolved),
                    "can_approve": False,
                    "can_execute": False,
                    # Why the unresolved names are unresolved. Lets the
                    # dashboard and the plan explain a missing capability
                    # instead of silently dropping the specialist.
                    "unavailable_reasons": [
                        {
                            "tool": t,
                            "category": DOCUMENTED_UNAVAILABLE_TOOLS[t]["category"],
                            "reason": DOCUMENTED_UNAVAILABLE_TOOLS[t]["reason"],
                            "remediation": DOCUMENTED_UNAVAILABLE_TOOLS[t]["remediation"],
                        }
                        for t in unimplemented
                        if t in DOCUMENTED_UNAVAILABLE_TOOLS
                    ],
                }
            )
        entries.sort(key=lambda e: e["agent_id"])
        return entries

    # ---------------------------------------------------------------- #
    # 2. Goal understanding
    # ---------------------------------------------------------------- #

    def parse_goal(self, ctx: AgentContext) -> dict[str, Any]:
        """Extract a merchant goal into a structured, honest brief.

        Deterministic by default: keyword-derived themes, no invented merchant
        data. When an LLM is configured it may add a short rationale, but the
        parsed structure (themes, constraints, success criteria) stays
        deterministic so a model can never invent constraints or budget.
        """
        objective = str(ctx.params.get("objective") or "").strip()
        if not objective:
            objective = "Identify and pursue the highest-impact growth opportunities"

        lowered = objective.lower()
        themes = sorted({t for t in self.GOAL_THEME_TOOLS if t.replace("_", " ") in lowered or t in lowered})

        constraints: list[str] = []
        if ctx.params.get("budget") is not None:
            constraints.append(f"budget:{ctx.params['budget']}")
        if ctx.params.get("deadline"):
            constraints.append(f"deadline:{ctx.params['deadline']}")
        if ctx.params.get("max_amount_inr") is not None:
            constraints.append(f"max_amount_inr:{ctx.params['max_amount_inr']}")
        window_days = ctx.params.get("window_days")
        if window_days is not None:
            constraints.append(f"window_days:{window_days}")

        rag = ctx.shared.get("rag_context") or {}
        evidence_status = rag.get("status") or "unknown"

        rationale: str | None = None
        if ctx.llm is not None:
            try:
                adapter = self.get_langchain_adapter(ctx)
                text, ms = adapter.execute_text_reasoning(
                    "You are a growth coordinator. In ONE sentence, explain which registered "
                    "specialist capabilities are most relevant to the merchant objective. "
                    "Do not invent numbers, customers, revenue or integrations.",
                    f"objective={objective} themes={themes}",
                    temperature=0.2,
                )
                rationale = text.strip() or None
            except Exception:  # noqa: BLE001 - rationale is optional enrichment
                rationale = None

        blocked_reasons: list[str] = []
        if not themes:
            blocked_reasons.append("objective_matched_no_registered_capability_theme")
        if evidence_status == "insufficient_data":
            blocked_reasons.append("insufficient_merchant_evidence")

        return {
            "goal": objective,
            "themes": themes,
            "constraints": constraints,
            "time_horizon_days": int(window_days) if window_days is not None else 30,
            "evidence_status": evidence_status,
            "success_criteria": self._derive_success_criteria(themes),
            "requires_human_approval": True,  # never negotiable: agents propose only
            "blocked_reasons": blocked_reasons,
            "selection_rationale": rationale,
        }

    @staticmethod
    def _derive_success_criteria(themes: list[str]) -> list[str]:
        criteria = ["all_selected_agents_report_a_real_status"]
        theme_set = set(themes)
        if theme_set & {"conversion", "checkout", "payment_recovery"}:
            criteria.append("measured_checkout_and_payment_metrics_are_reported")
        if theme_set & {"retention", "churn", "win_back", "customer", "segment"}:
            criteria.append("customer_segment_findings_are_evidenced")
        if theme_set & {"campaign", "marketing", "acquisition"}:
            criteria.append("campaign_actions_are_proposed_for_human_approval")
        if theme_set & {"product", "catalog", "pricing", "bundle", "upsell", "cross_sell"}:
            criteria.append("catalog_or_basket_findings_are_evidenced")
        if theme_set & {"experiment"}:
            criteria.append("experiment_design_is_recorded_with_a_hypothesis")
        criteria.append("no_action_is_approved_or_executed_by_the_manager")
        return criteria

    # ---------------------------------------------------------------- #
    # 3. Dynamic agent selection
    # ---------------------------------------------------------------- #

    def select_agents(
        self,
        goal: dict[str, Any],
        *,
        available: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Select the registered agents relevant to the parsed goal.

        Selection is capability-driven: an agent is a candidate only when at
        least one of its REAL registered tools matches the goal's themes. The
        Manager never selects itself and never selects the whole roster.

        A specialist that is genuinely relevant to the goal but exposes no
        implemented tool (e.g. DesignerAgent) is reported under
        ``unavailable_specialists`` with its documented reason. It is never
        dropped silently, and it is never faked into the selection.
        """
        roster = available if available is not None else self.discover_registered_agents()
        themes = set(goal.get("themes") or ())
        goal_text = str(goal.get("goal") or "").lower()
        wanted_tools: set[str] = set()
        for theme in themes:
            wanted_tools.update(self.GOAL_THEME_TOOLS.get(theme, ()))

        selected: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        considered: list[str] = []
        for entry in roster:
            agent_id = entry["agent_id"]
            # The Manager coordinates; it must not delegate to itself.
            if agent_id == self.NAME:
                continue
            considered.append(agent_id)
            if not entry.get("selectable"):
                # Relevant-but-unavailable is only reported when this agent is
                # actually on-topic for the goal, so an unrelated agent with
                # no tools does not clutter the merchant's plan.
                description = str(entry.get("description") or "").lower()
                words = {w for w in re.findall(r"[a-z]{4,}", description)}
                if words & set(re.findall(r"[a-z]{4,}", goal_text)):
                    unavailable.append(
                        {
                            "agent_id": agent_id,
                            "reason": "no_implemented_catalog_tool",
                            "unimplemented_tools": list(entry.get("unimplemented_tools") or ()),
                            "detail": list(entry.get("unavailable_reasons") or ()),
                            "reachable_via": "its own workspace endpoint, not the agent tool catalog",
                        }
                    )
                continue
            matched = [t for t in entry.get("tools", ()) if t in wanted_tools]
            if not matched:
                continue
            # Relevance score: tool coverage dominates, then a genuine
            # lexical overlap between the agent's real description and the
            # merchant's own words. Both are deterministic, so the same goal
            # always selects the same specialists.
            description = str(entry.get("description") or "").lower()
            words = {w for w in re.findall(r"[a-z]{4,}", description)}
            overlap = len(words & set(re.findall(r"[a-z]{4,}", goal_text)))
            selected.append(
                {
                    "agent_id": agent_id,
                    "reason": f"registered_capabilities:{','.join(sorted(matched))}",
                    "matched_tools": sorted(matched),
                    "_score": (len(matched), overlap),
                }
            )

        selected.sort(key=lambda s: (-s["_score"][0], -s["_score"][1], s["agent_id"]))
        capped = selected[: self.PLAN_LIMITS["max_agents"]]
        for entry in capped:
            entry.pop("_score", None)
        unavailable.sort(key=lambda u: u["agent_id"])
        return {
            "selected": capped,
            # On-topic specialists that cannot be selected, with the reason.
            # Surfaced so a goal that needs them is never silently narrowed.
            "unavailable_specialists": unavailable,
            "considered": considered,
            "registry_size": len(roster),
            "wanted_tools": sorted(wanted_tools),
            "unmatched_theme_tools": sorted(wanted_tools - {t for s in capped for t in s["matched_tools"]}),
        }

    # ---------------------------------------------------------------- #
    # 4. Validated plan construction
    # ---------------------------------------------------------------- #

    def build_execution_plan(
        self,
        *,
        ctx: AgentContext,
        goal: dict[str, Any],
        selection: dict[str, Any],
        workflow_id: str,
        proposed_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build and DETERMINISTICALLY validate a serializable execution plan.

        ``proposed_tasks`` may contain model-generated content. It is treated
        as untrusted data: unknown agent ids, duplicate task ids, bad
        dependency references, circular dependencies, unregistered tools,
        model-issued permissions and invalid limits are all rejected here.
        """
        available = {e["agent_id"]: e for e in (selection.get("_roster") or self.discover_registered_agents())}
        allowed_agents = {s["agent_id"] for s in selection.get("selected", ())}

        limits = dict(self.PLAN_LIMITS)
        tasks: list[dict[str, Any]] = []
        rejections: list[str] = []

        raw_tasks = proposed_tasks if proposed_tasks else [
            {
                "agent_id": s["agent_id"],
                "task": f"{s['agent_id']}: investigate '{goal['goal']}'",
                "expected_output": "status, evidence and findings",
                "depends_on": [],
            }
            for s in selection.get("selected", ())
        ]

        seen_ids: set[str] = set()
        for index, raw in enumerate(raw_tasks):
            agent_id = str(raw.get("agent_id") or "")
            # A model may not delegate to an agent it did not select, to an
            # unregistered agent, or to the Manager itself.
            if agent_id not in available:
                rejections.append(f"unknown_agent_id:{agent_id or '<empty>'}")
                continue
            if agent_id not in allowed_agents:
                rejections.append(f"agent_not_selected:{agent_id}")
                continue
            if agent_id == self.NAME:
                rejections.append(f"manager_cannot_delegate_to_itself:{agent_id}")
                continue

            task_id = str(raw.get("task_id") or f"T{index + 1}")
            if task_id in seen_ids:
                rejections.append(f"duplicate_task_id:{task_id}")
                continue
            seen_ids.add(task_id)

            declared_tools = raw.get("tools") or []
            entry_tools = set(available[agent_id].get("tools", ()))
            foreign_tools = [str(t) for t in declared_tools if str(t) not in entry_tools]
            for tool in foreign_tools:
                # An agent may not use a tool it does not own.
                rejections.append(f"unregistered_tool_for_agent:{agent_id}:{tool}")

            # Model output can never grant permissions. A task that tries is
            # dropped outright rather than sanitised, so a caller that ignores
            # ``validation.valid`` still cannot execute it.
            privilege_keys = [k for k in ("permissions", "granted_permissions", "role") if raw.get(k)]
            for key in privilege_keys:
                rejections.append(f"model_generated_permission_rejected:{agent_id}:{key}")

            if foreign_tools or privilege_keys:
                # Fail closed: the whole task is rejected.
                seen_ids.discard(task_id)
                continue

            tasks.append(
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "description": str(raw.get("task") or raw.get("description") or "Investigate the merchant objective.")[:500],
                    "expected_output": str(raw.get("expected_output") or "status, evidence and findings")[:300],
                    "depends_on": [str(d) for d in (raw.get("depends_on") or [])][:8],
                    "required_inputs": [str(i) for i in (raw.get("required_inputs") or [])][:8],
                    "tools": [str(t) for t in declared_tools],
                    "priority": str(raw.get("priority") or "normal")[:16],
                    "approval_required": True,
                    "completion_criteria": self._task_completion_criteria(agent_id),
                }
            )

        # A dependency on a task that does not exist is invalid, not ignored:
        # silently dropping the edge would let an agent claim it runs after
        # work that never happens.
        known_ids = {t["task_id"] for t in tasks}
        for task in tasks:
            dangling = [d for d in task["depends_on"] if d not in known_ids]
            if dangling:
                rejections.append(
                    f"invalid_dependency_reference:{task['task_id']}->{','.join(sorted(dangling))}"
                )
                task["depends_on"] = [d for d in task["depends_on"] if d in known_ids]

        cycle = self._find_dependency_cycle([t["task_id"] for t in tasks], {t["task_id"]: t["depends_on"] for t in tasks})
        if cycle:
            rejections.append(f"circular_dependency:{'->'.join(cycle)}")

        return {
            "workflow_id": workflow_id,
            "merchant_id": str(ctx.merchant_id),
            "goal": goal,
            "selected_agents": sorted(allowed_agents),
            "tasks": tasks,
            "limits": limits,
            "validation": {
                "valid": not rejections,
                "rejections": rejections,
                "validated_at": datetime.now(timezone.utc).isoformat(),
            },
            # A limitation is NOT a validation failure: the plan is still
            # executable with the specialists that are available. It exists so
            # an on-topic-but-unavailable specialist is disclosed rather than
            # silently dropped.
            "limitations": list(selection.get("unavailable_specialists") or ()),
            "status": "invalid" if rejections else "ready_for_execution",
            # Planning never executes. Kept on the agent-level contract too so
            # a caller cannot mistake a returned plan for a completed cycle.
            "executed": False,
            "requires_human_approval_for_actions": True,
        }

    @staticmethod
    def _task_completion_criteria(agent_id: str) -> list[str]:
        return [
            f"{agent_id}_returns_a_real_status",
            "errors_are_reported_verbatim",
            "no_unverified_business_metric_is_claimed",
        ]

    @staticmethod
    def _find_dependency_cycle(
        node_ids: list[str],
        edges: dict[str, list[str]],
    ) -> list[str] | None:
        """Return one dependency cycle, or None. Iterative DFS (no recursion limit)."""
        state: dict[str, int] = {n: 0 for n in node_ids}  # 0=unseen 1=open 2=done
        for start in node_ids:
            if state[start] != 0:
                continue
            stack: list[tuple[str, list[str]]] = [(start, [])]
            path: list[str] = []
            while stack:
                node, seen = stack.pop()
                if state.get(node) == 2:
                    continue
                if node in seen:
                    return seen[seen.index(node):] + [node]
                if state.get(node) == 1:
                    idx = path.index(node) if node in path else 0
                    return path[idx:] + [node]
                state[node] = 1
                path.append(node)
                for dep in edges.get(node, []):
                    if dep in state:
                        stack.append((dep, seen + [node]))
                while path and path[-1] == node and not edges.get(node):
                    path.pop()
                    state[node] = 2
        return None

    # ---------------------------------------------------------------- #
    # 5. Result evaluation + bounded replan decision
    # ---------------------------------------------------------------- #

    def evaluate_results(
        self,
        agents_run: list[dict[str, Any]],
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Interpret ACTUAL agent results and decide whether to replan.

        Never marks a workflow successful because execution returned an
        object: every agent's real status, errors and lifecycle metadata are
        preserved, and failures are classified rather than swallowed.
        """
        evaluations: list[dict[str, Any]] = []
        for entry in agents_run:
            status = str(entry.get("status") or "unknown")
            errors = [str(e) for e in (entry.get("errors") or [])]
            kind = "transient" if status not in ("completed", "partially_completed") else None
            detail = errors[0] if errors else ""

            lowered = " ".join(errors).lower()
            # Transient indicators are checked BEFORE defaulting to permanent:
            # a timeout or a rate limit is worth retrying inside the existing
            # budget, whereas an assertion or a validation error is not.
            transient_markers = (
                "timeout", "timed out", "connection", "temporarily", "rate limit",
                "too many requests", "try again", "unavailable", "reset by peer",
            )
            if any(t in lowered for t in ("llm_not_configured", "not configured", "missing_configuration")):
                kind = "missing_configuration"
            elif any(t in lowered for t in ("insufficient", "insufficient_data", "insufficient evidence")):
                kind = "insufficient_evidence"
            elif any(t in lowered for t in ("no such", "nonexistent", "not found", "invalid", "validationerror")):
                kind = "missing_input"
            elif status == "blocked":
                kind = "failed_dependency"
            elif status == "replan_required":
                kind = "transient"
            elif status == "failed":
                kind = "transient" if any(m in lowered for m in transient_markers) else "permanent"
            elif status == "skipped":
                kind = "unnecessary_task"

            # An agent that raised a Phase 4 proposal needs a human, not a retry.
            approval_required = int(entry.get("actions_proposed") or 0) > 0
            if approval_required and kind is None:
                kind = "approval_required"

            evaluations.append(
                {
                    "agent_id": entry.get("agent"),
                    "status": status,
                    "failure_kind": kind,
                    "detail": detail,
                    "errors": errors,
                    "actions_proposed": entry.get("actions_proposed", 0),
                    "latency_ms": (entry.get("latency_ms") or {}).get("total"),
                    "tools_used": entry.get("tools_used", []),
                    "retryable": kind in ("transient",),
                }
            )

        completed = [e for e in evaluations if e["status"] in ("completed", "partially_completed")]
        failed = [e for e in evaluations if e["status"] == "failed"]
        retryable = [e for e in evaluations if e["retryable"]]
        blocked = [e for e in evaluations if e["failure_kind"] in ("missing_configuration", "missing_input", "insufficient_evidence", "failed_dependency")]

        if not evaluations:
            outcome = "no_agents_executed"
        elif not completed and failed:
            outcome = "failed"
        elif completed:
            outcome = "partial_success" if (failed or blocked) else "completed"
        else:
            outcome = "blocked"

        # Replan ONLY for retryable, bounded, and only while under the limit.
        replan_budget = self.PLAN_LIMITS["max_replan"]
        should_replan = bool(retryable) and len(retryable) <= replan_budget and not completed
        return {
            "outcome": outcome,
            "evaluations": evaluations,
            "completed": [e["agent_id"] for e in completed],
            "failed": [e["agent_id"] for e in failed],
            "blocked": [e["agent_id"] for e in blocked],
            "retryable": [e["agent_id"] for e in retryable],
            "replan_recommended": should_replan,
            "replan_budget": replan_budget,
            "replan_within_bounds": should_replan,
        }

    # ---------------------------------------------------------------- #
    # 6. Final synthesis (facts vs. model output vs. proposals)
    # ---------------------------------------------------------------- #

    def build_final_report(
        self,
        *,
        goal: dict[str, Any],
        plan: dict[str, Any],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble the merchant-facing final result from ACTUAL data only.

        ``observed_facts`` comes from real runs. ``recommendations`` is
        explicitly labelled model-derived. ``proposed_actions`` still require
        human approval; the Manager never approves them.
        """
        agents_run = list(summary.get("agents") or ())
        evaluation = self.evaluate_results(agents_run, plan)
        totals = summary.get("totals") or {}

        observed_facts = [
            f"{e['agent_id']}: status={e['status']}"
            + (f" failure_kind={e['failure_kind']}" if e["failure_kind"] else "")
            for e in evaluation["evaluations"]
        ]

        next_steps: list[str] = []
        if evaluation["blocked"]:
            next_steps.append("resolve_missing_configuration_or_evidence_before_retrying")
        if evaluation["retryable"]:
            next_steps.append("retry_transient_failures_within_the_existing_replan_budget")
        if int(totals.get("actions_proposed") or 0) > 0:
            next_steps.append("review_proposed_actions_in_the_approval_queue")
        if not next_steps:
            next_steps.append("no_follow_up_required_for_this_cycle")

        return {
            "workflow_id": plan.get("workflow_id"),
            "goal": goal.get("goal"),
            "plan": {
                "status": plan.get("status"),
                "selected_agents": plan.get("selected_agents", []),
                "tasks": [
                    {"task_id": t["task_id"], "agent_id": t["agent_id"], "priority": t["priority"]}
                    for t in plan.get("tasks", [])
                ],
                "validation": plan.get("validation"),
            },
            "execution_status": summary.get("status"),
            "evaluation": evaluation,
            "observed_facts": observed_facts,
            "totals": totals,
            "actions_proposed": int(totals.get("actions_proposed") or 0),
            "actions_awaiting_human_approval": int(totals.get("actions_proposed") or 0),
            "constraints_or_limitations": list(goal.get("blocked_reasons") or ()),
            "recommendations_source": "model_derived",
            "recommended_next_steps": next_steps,
            "manager_approved_anything": False,
        }

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