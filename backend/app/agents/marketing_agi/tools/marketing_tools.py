"""Marketing knowledge tools — campaign history, memory, previous results.

These tools let the agent ask: what has been tried before, what worked,
what failed, and what does the merchant prefer — grounding every new
decision in history instead of repeating mistakes.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.campaign import Campaign
from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import AgentActionStatus
from backend.app.services.memory import GrowthMemoryService
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

MARKETING_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_campaign_history",
        category="marketing",
        description="All previous campaigns with status and estimated revenue.",
        capabilities=["campaigns", "history"],
    ),
    ToolSpec(
        name="get_action_history",
        category="marketing",
        description="Previously proposed/approved/rejected agent actions — the agent learns what merchants accept.",
        capabilities=["actions", "history"],
    ),
    ToolSpec(
        name="recall_memory",
        category="knowledge",
        description=(
            "Semantic recall of growth memories (strategy outcomes, campaign "
            "results, preferences) relevant to a question."
        ),
        capabilities=["memory", "learning"],
    ),
]


def get_campaign_history(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 30
) -> dict[str, Any]:
    campaigns = list(
        db.scalars(
            select(Campaign)
            .where(Campaign.merchant_id == merchant_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        ).all()
    )
    return {
        "campaign_count": len(campaigns),
        "campaigns": [
            {
                "campaign_id": str(c.id),
                "name": c.name,
                "type": str(getattr(c.type, "value", c.type)),
                "status": str(getattr(c.status, "value", c.status)),
                "target_count": int(c.target_count or 0),
                "estimated_revenue_inr": (
                    float(c.estimated_revenue) if c.estimated_revenue else None
                ),
                "actual_revenue_inr": float(c.actual_revenue) if c.actual_revenue else None,
            }
            for c in campaigns
        ],
    }


def get_action_history(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 30
) -> dict[str, Any]:
    actions = list(
        db.scalars(
            select(AgentAction)
            .where(AgentAction.merchant_id == merchant_id)
            .order_by(AgentAction.created_at.desc())
            .limit(limit)
        ).all()
    )
    return {
        "action_count": len(actions),
        "actions": [
            {
                "action_id": str(a.id),
                "action_type": str(getattr(a.action_type, "value", a.action_type)),
                "status": str(getattr(a.status, "value", a.status)),
                "requested_by": a.requested_by,
                "approved_by": a.approved_by,
                "created_at": str(a.created_at),
            }
            for a in actions
        ],
    }


def recall_memory(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    query: str,
    k: int = 5,
) -> dict[str, Any]:
    """Merchant-scoped memory recall — never crosses tenants."""
    service = GrowthMemoryService(db)
    memories = service.retrieve(merchant_id, query, k=k)
    return {
        "query": query,
        "memory_count": len(memories),
        "memories": memories,
    }


def register(registry) -> None:
    from backend.app.agents.marketing_agi.tools.registry import ToolContext

    def _mk(fn, **fixed):
        def factory(ctx: ToolContext):
            def call(**kwargs):
                if ctx.embedding_provider is not None and "query" in kwargs:
                    service = GrowthMemoryService(ctx.db, ctx.embedding_provider)
                    memories = service.retrieve(
                        ctx.merchant_id, kwargs["query"], k=kwargs.get("k", 5)
                    )
                    return {
                        "query": kwargs["query"],
                        "memory_count": len(memories),
                        "memories": memories,
                    }
                merged = {**fixed, **kwargs}
                return fn(ctx.db, ctx.merchant_id, **merged)
            return call
        return factory

    registry.register(MARKETING_TOOLS[0], _mk(get_campaign_history, limit=30))
    registry.register(MARKETING_TOOLS[1], _mk(get_action_history, limit=30))
    # recall_memory handled specially in factory for embedding support
    def _recall_factory(ctx: ToolContext):
        def call(query: str, k: int = 5):
            service = GrowthMemoryService(ctx.db, ctx.embedding_provider)
            memories = service.retrieve(ctx.merchant_id, query, k=k)
            return {
                "query": query,
                "memory_count": len(memories),
                "memories": memories,
            }
        return call

    registry.register(MARKETING_TOOLS[2], _recall_factory)
