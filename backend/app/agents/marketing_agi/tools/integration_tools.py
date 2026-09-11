"""Integration boundary tools — email, Google Ads, Meta Ads, social.

NO FAKE INTEGRATIONS (hard rule):
  - The platform has NO live email/ads/social API integrations today.
  - These tools therefore expose only READ operations against the
    platform's own real data (campaigns/actions stored in OUR database),
    plus DRAFT/PREPARE operations that persist work products locally.
  - Every prepared artifact carries integration_status:
        "draft_only"            — real draft stored in OUR db
        "requires_integration" — external execution impossible today
  - Nothing here ever claims an external message was sent or an ad was
    changed. Execution still goes through the human-approved Phase 4
    action pipeline (SendCampaignExecutor is test-mode and says so).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import AgentActionStatus
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

INTEGRATION_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_email_campaigns",
        category="integrations",
        description=(
            "Email-type campaigns recorded on the platform with performance "
            "fields, from OUR real campaign store (no external ESP connected)."
        ),
        capabilities=["email", "campaign_performance"],
        integration_status="draft_only",
    ),
    ToolSpec(
        name="get_email_campaign_performance",
        category="integrations",
        description=(
            "Real recorded outcomes (estimated vs actual revenue) for email "
            "campaigns. Honest: no click/open metrics exist without an ESP."
        ),
        capabilities=["email", "campaign_performance"],
        integration_status="draft_only",
    ),
    ToolSpec(
        name="create_email_campaign_draft",
        category="integrations",
        description=(
            "Persist a complete email campaign draft (audience criteria, "
            "message, variants, CTA, timing) as a MarketingAGICampaign. "
            "Status is DRAFT — external sending requires integration + approval."
        ),
        capabilities=["email", "draft"],
        integration_status="draft_only",
    ),
    ToolSpec(
        name="get_google_ads_campaigns",
        category="integrations",
        description=(
            "Google Ads inspection boundary. No Google Ads account is "
            "connected to this platform — the tool reports this honestly "
            "instead of returning fabricated metrics."
        ),
        capabilities=["google_ads"],
        integration_status="requires_integration",
    ),
    ToolSpec(
        name="get_meta_campaigns",
        category="integrations",
        description=(
            "Meta Ads inspection boundary. No Meta Ads account is connected — "
            "the tool reports this honestly instead of fabricating spend/CTR."
        ),
        capabilities=["meta_ads"],
        integration_status="requires_integration",
    ),
    ToolSpec(
        name="get_social_performance",
        category="integrations",
        description=(
            "Social platform boundary. No social API is connected — the tool "
            "reports this honestly; post concepts are prepared as drafts only."
        ),
        capabilities=["social"],
        integration_status="requires_integration",
    ),
]


def get_email_campaigns(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    from backend.app.models.campaign import Campaign
    from backend.app.models.enums import CampaignType

    rows = list(
        db.scalars(
            select(Campaign)
            .where(
                Campaign.merchant_id == merchant_id,
                Campaign.type == CampaignType.email,
            )
            .order_by(Campaign.created_at.desc())
        ).all()
    )
    return {
        "source": "platform_campaign_store",
        "connected_esp": False,
        "campaigns": [
            {
                "campaign_id": str(c.id),
                "name": c.name,
                "status": str(getattr(c.status, "value", c.status)),
                "target_count": int(c.target_count or 0),
                "estimated_revenue_inr": (
                    float(c.estimated_revenue) if c.estimated_revenue else None
                ),
                "actual_revenue_inr": (
                    float(c.actual_revenue) if c.actual_revenue else None
                ),
            }
            for c in rows
        ],
        "note": "No external email service provider is connected; these are platform-recorded campaigns.",
    }


def get_email_campaign_performance(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Honest performance picture from recorded data only."""
    base = get_email_campaigns(db, merchant_id)
    with_results = [
        c for c in base["campaigns"] if c["actual_revenue_inr"] is not None
    ]
    return {
        **base,
        "metrics_available": ["estimated_revenue", "actual_revenue", "target_count"],
        "metrics_unavailable": ["opens", "clicks", "bounces", "unsubscribes"],
        "unavailable_reason": "Requires a connected email service provider.",
        "campaigns_with_measured_results": len(with_results),
    }


def create_email_campaign_draft(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    campaign_key: str,
    workflow: str,
    name: str,
    objective: str,
    audience: dict[str, Any],
    audience_count: int,
    content: dict[str, Any],
    expected_impact: dict[str, Any],
    success_metric: str,
    evidence_refs: list[str],
    run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Persist a real campaign draft in the MarketingAGI workspace.

    Integration status is draft_only: nothing external is claimed.
    """
    from backend.app.models.marketing_agi import MarketingAGICampaign
    from decimal import Decimal

    existing = db.scalar(
        select(MarketingAGICampaign).where(
            MarketingAGICampaign.merchant_id == merchant_id,
            MarketingAGICampaign.campaign_key == campaign_key,
        )
    )
    if existing is not None:
        return {
            "created": False,
            "status": "duplicate_prevented",
            "campaign_id": str(existing.id),
            "campaign_key": campaign_key,
        }

    est = expected_impact.get("estimated_revenue_inr")
    row = MarketingAGICampaign(
        merchant_id=merchant_id,
        run_id=run_id,
        campaign_key=campaign_key,
        workflow=workflow,
        name=name,
        objective=objective,
        channel="email",
        integration_status="draft_only",
        lifecycle="draft",
        audience=audience,
        audience_count=int(audience_count),
        content=content,
        expected_impact=expected_impact,
        estimated_revenue=Decimal(str(est)) if est is not None else None,
        success_metric=success_metric,
        evidence_refs=evidence_refs,
    )
    db.add(row)
    db.flush()
    return {
        "created": True,
        "status": "draft_created",
        "integration_status": "draft_only",
        "campaign_id": str(row.id),
        "campaign_key": campaign_key,
        "note": "Draft stored on the platform. External sending requires an email integration and human approval.",
    }


def _unavailable(platform: str, missing_env: list[str]) -> dict[str, Any]:
    return {
        "connected": False,
        "platform": platform,
        "status": "requires_integration",
        "missing_configuration": missing_env,
        "campaigns": None,
        "metrics": None,
        "note": (
            f"No {platform} integration is connected to this platform. "
            "Metrics are not fabricated. Connect the integration to enable live inspection."
        ),
    }


def get_google_ads_campaigns(**_: Any) -> dict[str, Any]:
    return _unavailable(
        "Google Ads",
        ["GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_REFRESH_TOKEN"],
    )


def get_meta_campaigns(**_: Any) -> dict[str, Any]:
    return _unavailable("Meta Ads", ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"])


def get_social_performance(**_: Any) -> dict[str, Any]:
    return _unavailable("Social Platforms", ["SOCIAL_PLATFORM_CONNECTIONS"])


def register(registry) -> None:
    from backend.app.agents.marketing_agi.tools.registry import ToolContext

    def _mk(fn, **fixed):
        def factory(ctx: ToolContext):
            def call(**kwargs):
                if fn in (get_google_ads_campaigns, get_meta_campaigns, get_social_performance):
                    return fn(**kwargs)
                merged = {**fixed, **kwargs}
                return fn(ctx.db, ctx.merchant_id, **merged)
            return call
        return factory

    registry.register(INTEGRATION_TOOLS[0], _mk(get_email_campaigns))
    registry.register(INTEGRATION_TOOLS[1], _mk(get_email_campaign_performance))
    registry.register(INTEGRATION_TOOLS[2], _mk(create_email_campaign_draft))
    registry.register(INTEGRATION_TOOLS[3], _mk(get_google_ads_campaigns))
    registry.register(INTEGRATION_TOOLS[4], _mk(get_meta_campaigns))
    registry.register(INTEGRATION_TOOLS[5], _mk(get_social_performance))
