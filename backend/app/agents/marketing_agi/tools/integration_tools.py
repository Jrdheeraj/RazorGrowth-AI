"""Integration tools — email, Google Ads, Meta Ads, social.

NO FAKE INTEGRATIONS (hard rule):
  - Read tools query LIVE provider APIs when the merchant has a verified
    connection row (see services/integration_service); otherwise they
    return an honest requires_integration payload — never fabricated data.
  - Email reads always work against the platform's own campaign store;
    they additionally report the real Resend connection state.
  - Draft/preparation tools persist work products locally (draft_only).
  - External writes NEVER happen here: send/publish/create run exclusively
    through the human-approved action pipeline (services/action_executor).
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
            "fields, from OUR real campaign store, plus the real Resend "
            "connection state (sending identity when connected)."
        ),
        capabilities=["email", "campaign_performance"],
        integration_status="draft_only",
        provider="resend",
        requires_connection=False,
        read_only=True,
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
        provider="resend",
        requires_connection=False,
        read_only=True,
    ),
    ToolSpec(
        name="create_email_campaign_draft",
        category="integrations",
        description=(
            "Persist a complete email campaign draft (audience criteria, "
            "message, variants, CTA, timing) as a MarketingAGICampaign. "
            "Status is DRAFT — sending (send_email) requires a verified "
            "Resend connection AND human approval via the actions pipeline."
        ),
        capabilities=["email", "draft"],
        integration_status="draft_only",
        provider="resend",
        requires_connection=False,
        read_only=False,
        write_actions=["send_email"],
        writes_require_approval=True,
    ),
    ToolSpec(
        name="get_google_ads_campaigns",
        category="integrations",
        description=(
            "Google Ads campaigns + metrics from the LIVE Google Ads API "
            "when the merchant connected a verified account; otherwise an "
            "honest requires_integration payload — never fabricated data."
        ),
        capabilities=["google_ads"],
        integration_status="requires_integration",
        provider="google_ads",
        requires_connection=True,
        read_only=True,
        write_actions=["create_campaign_paused"],
        writes_require_approval=True,
    ),
    ToolSpec(
        name="get_meta_campaigns",
        category="integrations",
        description=(
            "Meta ad campaigns + 30-day insights from the LIVE Marketing API "
            "when connected; otherwise honest requires_integration."
        ),
        capabilities=["meta_ads"],
        integration_status="requires_integration",
        provider="meta_ads",
        requires_connection=True,
        read_only=True,
        write_actions=["create_campaign_paused"],
        writes_require_approval=True,
    ),
    ToolSpec(
        name="get_social_performance",
        category="integrations",
        description=(
            "Instagram business identity from the LIVE Graph API when "
            "connected; post concepts are drafts only, publishing needs "
            "human approval. Never fabricated."
        ),
        capabilities=["social"],
        integration_status="requires_integration",
        provider="instagram",
        requires_connection=True,
        read_only=True,
        write_actions=["publish_photo"],
        writes_require_approval=True,
    ),
]


def _resend_connection_state(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Real Resend connection state for this merchant (no secrets)."""
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "resend")
    if row is None:
        return {"connected_esp": False}
    meta = dict(row.connection_metadata or {})
    return {
        "connected_esp": True,
        "from_email": meta.get("from_email"),
        "from_name": meta.get("from_name"),
        "domain_count": meta.get("domain_count", 0),
        "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
    }


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
    esp = _resend_connection_state(db, merchant_id)
    return {
        "source": "platform_campaign_store",
        **esp,
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
        "note": (
            "Platform-recorded campaigns."
            + (
                " Resend is connected — sending requires human approval."
                if esp.get("connected_esp")
                else " No email provider connected; sending is impossible."
            )
        ),
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


def _unavailable(platform: str, missing: list[str], provider: str) -> dict[str, Any]:
    return {
        "connected": False,
        "platform": platform,
        "provider": provider,
        "status": "requires_integration",
        "missing_configuration": missing,
        "campaigns": None,
        "metrics": None,
        "note": (
            f"No {platform} connection is verified for this workspace. "
            "Metrics are not fabricated. Connect the integration to enable live inspection."
        ),
    }


def _google_live_context(
    db: Session, merchant_id: uuid.UUID
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (live_ctx, unavailable_payload). live_ctx holds a fresh
    access token + ids for one live API call; never cached, never logged."""
    from backend.app.core.config import get_settings
    from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "google_ads")
    if row is None:
        return None, _unavailable(
            "Google Ads",
            ["Connect Google Ads from the Marketing Agent workstation (OAuth)."],
            "google_ads",
        )
    creds = svc.decrypt_credentials(row)
    settings = get_settings()
    adapter = GoogleAdsProvider()
    tok = adapter.refresh_access_token(
        refresh_token=creds.get("refresh_token", ""),
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )
    if not tok.ok:
        return None, {
            "connected": False,
            "platform": "Google Ads",
            "provider": "google_ads",
            "status": "error",
            "error_code": tok.error_code,
            "message": tok.message,
            "campaigns": None,
            "metrics": None,
        }
    meta = dict(row.connection_metadata or {})
    return {
        "access_token": tok.data["access_token"],
        "developer_token": creds.get("developer_token") or settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "customer_id": meta.get("customer_id") or row.account_id,
        "login_customer_id": meta.get("customer_id"),
        "api_version": settings.GOOGLE_ADS_API_VERSION,
        "account_name": row.account_name,
    }, None


def get_google_ads_campaigns(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Live Google Ads campaigns when connected; honest payload otherwise."""
    from backend.app.integrations.marketing.google_ads import GoogleAdsProvider

    live, unavailable = _google_live_context(db, merchant_id)
    if unavailable is not None:
        return unavailable
    assert live is not None
    result = GoogleAdsProvider().list_campaigns(
        access_token=live["access_token"],
        developer_token=live["developer_token"],
        customer_id=live["customer_id"],
        login_customer_id=live["login_customer_id"],
        api_version=live["api_version"],
    )
    if not result.ok:
        return {
            "connected": True,
            "platform": "Google Ads",
            "provider": "google_ads",
            "status": "error",
            "error_code": result.error_code,
            "message": result.message,
            "campaigns": None,
            "metrics": None,
        }
    return {
        "connected": True,
        "platform": "Google Ads",
        "provider": "google_ads",
        "status": "connected",
        "account": {"customer_id": live["customer_id"], "customer_name": live["account_name"]},
        "campaigns": result.data.get("campaigns", []),
        "metrics": None,
        "note": "Live data from the Google Ads API.",
    }


def _meta_live_token(
    db: Session, merchant_id: uuid.UUID
) -> tuple[str | None, dict[str, Any] | None]:
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "meta_ads")
    if row is None:
        return None, _unavailable(
            "Meta Ads",
            ["Connect Meta Ads from the Marketing Agent workstation (OAuth)."],
            "meta_ads",
        )
    token = svc.decrypt_credentials(row).get("access_token", "")
    if not token:
        return None, _unavailable("Meta Ads", ["Stored credentials are unreadable — reconnect."], "meta_ads")
    return token, None


def get_meta_campaigns(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Live Meta campaigns + insights when connected; honest otherwise."""
    from backend.app.core.config import get_settings
    from backend.app.integrations.marketing.meta_ads import MetaAdsProvider
    from backend.app.services import integration_service as svc

    token, unavailable = _meta_live_token(db, merchant_id)
    if unavailable is not None:
        return unavailable
    assert token is not None
    settings = get_settings()
    row = svc.connected_row(db, merchant_id, "meta_ads")
    meta = dict((row.connection_metadata if row else {}) or {})
    result = MetaAdsProvider().list_campaigns(
        access_token=token,
        ad_account_id=meta.get("ad_account_id") or (row.account_id if row else ""),
        graph_version=settings.META_GRAPH_VERSION,
    )
    if not result.ok:
        return {
            "connected": True,
            "platform": "Meta Ads",
            "provider": "meta_ads",
            "status": "error",
            "error_code": result.error_code,
            "message": result.message,
            "campaigns": None,
            "metrics": None,
        }
    return {
        "connected": True,
        "platform": "Meta Ads",
        "provider": "meta_ads",
        "status": "connected",
        "account": {"ad_account_id": result.data.get("ad_account_id"), "ad_account_name": row.account_name if row else None},
        "campaigns": result.data.get("campaigns", []),
        "metrics": None,
        "note": "Live data from the Meta Marketing API (last-30-day insights).",
    }


def get_social_performance(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Live Instagram identity when connected; honest otherwise.

    No engagement metrics are fabricated: without a connected account the
    tool reports requires_integration; with one it reports the verified
    identity (drafts + approval-gated publishing only).
    """
    from backend.app.core.config import get_settings
    from backend.app.integrations.marketing.instagram import InstagramProvider
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "instagram")
    if row is None:
        return _unavailable(
            "Instagram",
            ["Connect Instagram from the Marketing Agent workstation (Meta OAuth)."],
            "instagram",
        )
    settings = get_settings()
    token = svc.decrypt_credentials(row).get("access_token", "")
    result = InstagramProvider().verify(
        access_token=token,
        page_id=(dict(row.connection_metadata or {}).get("page_id")),
        graph_version=settings.META_GRAPH_VERSION,
    )
    if not result.ok:
        return {
            "connected": True,
            "platform": "Instagram",
            "provider": "instagram",
            "status": "error",
            "error_code": result.error_code,
            "message": result.message,
            "campaigns": None,
            "metrics": None,
        }
    return {
        "connected": True,
        "platform": "Instagram",
        "provider": "instagram",
        "status": "connected",
        "account": result.account,
        "campaigns": None,
        "metrics": None,
        "metrics_unavailable": ["impressions", "reach", "engagement"],
        "unavailable_reason": "Post-level metrics require published content; drafts and publishing need human approval.",
        "note": "Verified Instagram business identity. Content is drafted locally; publishing requires approval.",
    }


def register(registry) -> None:
    from backend.app.agents.marketing_agi.tools.registry import ToolContext

    def _mk(fn, **fixed):
        def factory(ctx: ToolContext):
            def call(**kwargs):
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
