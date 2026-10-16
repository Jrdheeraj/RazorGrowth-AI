"""
PersonalizationAgent — per-customer next-best-action recommendations.

Scope discipline (this agent does NOT):
  * recompute LTV / churn / segment — it consumes
    :class:`~backend.app.services.customer_intelligence.CustomerIntelligenceService`;
  * compute product affinity — it consumes
    :mod:`backend.app.services.product_intelligence`;
  * send anything — delivery belongs to the approval-gated Marketing path;
  * change a price, a catalogue entry or a payment.

It decides, explains, and measures. That is all.

Autonomy: the agent runs end to end without human input, but every output
is a *recommendation*. It holds no ``PROPOSE_ACTION`` permission by default
precisely because acting on its own recommendations would bypass the human
approval gate that protects the merchant.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    READ_CUSTOMERS,
    READ_OPPORTUNITIES,
    READ_PRODUCTS,
)
from backend.app.services.handoff import handoff_service
from backend.app.services.personalization import (
    ACTION_HOLD,
    PersonalizationService,
)

log = logging.getLogger(__name__)


class PersonalizationAgent(BaseGrowthAgent):
    NAME = "PersonalizationAgent"
    DESCRIPTION = (
        "Produces explainable per-customer next-best-action recommendations "
        "from real customer intelligence and basket affinity, assigns a "
        "deterministic treatment/control cohort, and measures observed "
        "outcomes once follow-up data exists."
    )
    #: Narrowly scoped. Note the absence of PROPOSE_ACTION: this agent
    #: recommends, it does not act. READ_PAYMENTS is deliberately excluded —
    #: it needs to know a customer *has* a failure, which the payment failure
    #: analytics surface already supplies at merchant scope.
    PERMISSIONS = frozenset({READ_CUSTOMERS, READ_PRODUCTS, READ_OPPORTUNITIES})
    TOOLS = ("customer.insights", "commerce.catalog_intelligence")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        control_ratio = float(ctx.params.get("control_ratio", 0.5))
        window_days = int(ctx.params.get("window_days", 30))

        svc = PersonalizationService(db)
        outcome = svc.decide(
            merchant_id,
            control_ratio=control_ratio,
            window_days=window_days,
        )
        result.output["personalization"] = outcome
        result.insights_generated = outcome["decisions"]
        result.tools_used.append("customer.insights")
        result.tools_used.append("commerce.catalog_intelligence")

        if outcome["decisions"] == 0:
            result.output["decision"] = "INSUFFICIENT_EVIDENCE"
            result.output["summary"] = (
                "No customer qualified for a personalized recommendation. "
                f"Skipped: {outcome['skipped_no_insight']} without a computed "
                f"customer insight, {outcome['skipped_insufficient_history']} "
                "without purchase history."
            )
            return

        actionable = outcome["decisions"] - outcome["by_action"].get(ACTION_HOLD, 0)
        result.output["actionable_decisions"] = actionable
        result.output["hold_decisions"] = outcome["by_action"].get(ACTION_HOLD, 0)

        # ── measurement pass (only meaningful once outcomes exist) ────────
        measurement = svc.measure_outcomes(merchant_id, window_days=window_days)
        result.output["measurement"] = measurement

        # ── structured handoff to Marketing (aggregate only, no PII) ───────
        try:
            handoff = handoff_service.request(
                db,
                merchant_id=merchant_id,
                source_agent=self.NAME,
                destination_agent="CampaignStrategistAgent",
                task=(
                    "Build audiences from the per-customer next-best-action "
                    "decisions for the treatment cohort only; the control "
                    "cohort must receive nothing."
                ),
                payload={
                    "objective": "Personalized re-engagement",
                    "by_action": outcome["by_action"],
                    "cohorts": {
                        "treatment": "act on these recommendations",
                        "control": "DO NOT contact — required for measurement",
                    },
                    "control_ratio": outcome["control_ratio"],
                },
                correlation_id=ctx.params.get("orchestrator_run_id"),
            )
            result.output["marketing_handoff"] = {
                "handoff_id": handoff["handoff_id"],
                "status": handoff["status"],
            }
        except Exception as exc:
            result.errors.append(f"marketing_handoff_skipped: {type(exc).__name__}")

        result.output["summary"] = (
            f"{actionable} of {outcome['decisions']} customer(s) received an "
            f"actionable next-best-action recommendation across "
            f"{len(outcome['by_action'])} distinct action(s). "
            + (
                f"Measured relative lift: {measurement['relative_lift']:.1%}."
                if measurement.get("is_significant")
                else "No uplift claimed yet — "
                + str(measurement.get("note", "insufficient cohort size"))
            )
        )