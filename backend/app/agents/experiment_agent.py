"""ExperimentAgent — proposes A/B tests for top opportunities (Feature 9)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, READ_OPPORTUNITIES
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.experiment_service import ExperimentService

log = logging.getLogger(__name__)


class ExperimentAgent(BaseGrowthAgent):
    NAME = "ExperimentAgent"
    DESCRIPTION = (
        "Designs honest A/B experiments (control vs treatment) around the "
        "top opportunity; results stay measurement_pending until real data "
        "exists."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("experiment_design",)

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        self._require(READ_OPPORTUNITIES)
        db = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        opportunity = db.scalars(
            select(GrowthOpportunity)
            .where(
                GrowthOpportunity.merchant_id == merchant_id,
                GrowthOpportunity.status == "pending_approval",
            )
            .order_by(GrowthOpportunity.expected_revenue.desc())
            .limit(1)
        ).first()
        if opportunity is None:
            result.output["note"] = "No pending opportunity to experiment on."
            return

        svc = ExperimentService(db)
        name = f"A/B: {opportunity.title[:80]}"
        exp = svc.create_experiment(
            merchant_id=merchant_id,
            name=name,
            hypothesis=(
                f"Treating the {opportunity.type} audience changes conversion "
                f"versus control. To be verified with real data."
            ),
            opportunity_id=opportunity.id,
            control_group={"offer": "none"},
            treatment_group={
                "offer": ctx.params.get("treatment_offer", "10% discount")
            },
            target_population_size=int(opportunity.target_customer_count or 0),
            estimated_metric={
                "estimated_additional_revenue": float(opportunity.expected_revenue),
                "is_estimate": True,
            },
        )
        result.experiments_proposed += 1
        result.output["experiment"] = {
            "experiment_id": str(exp.id),
            "status": str(exp.status),
            "name": exp.name,
        }
