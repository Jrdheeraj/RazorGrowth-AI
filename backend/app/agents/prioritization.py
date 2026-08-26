"""OpportunityPrioritizationAgent — deterministic ranking (Feature 2 output)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, READ_OPPORTUNITIES
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)


class OpportunityPrioritizationAgent(BaseGrowthAgent):
    NAME = "OpportunityPrioritizationAgent"
    DESCRIPTION = (
        "Scores and ranks open opportunities with the deterministic "
        "scoring engine so humans see the best-first queue."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("opportunity_scoring",)

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        self._require(READ_OPPORTUNITIES)
        db = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        limit = int(ctx.params.get("rank_limit", 10))

        opportunities = list(
            db.scalars(
                select(GrowthOpportunity)
                .where(
                    GrowthOpportunity.merchant_id == merchant_id,
                    GrowthOpportunity.status.in_(
                        ["pending_approval", "approved"]
                    ),
                )
                .limit(100)
            ).all()
        )
        engine = OpportunityScoringEngine()
        ranked = []
        for opp in opportunities:
            bd = engine.score(
                expected_revenue=float(opp.expected_revenue),
                confidence=float(opp.confidence),
                target_customer_count=int(opp.target_customer_count or 0),
                evidence_items=max(1, len(opp.reasoning or [])),
            )
            ranked.append((bd.opportunity_score, opp.id, opp.title))
        ranked.sort(key=lambda t: t[0], reverse=True)

        ctx.shared["ranked_opportunities"] = [
            {"opportunity_id": str(oid), "score": s, "title": t}
            for s, oid, t in ranked[:limit]
        ]
        result.output["ranked"] = ctx.shared["ranked_opportunities"]
