"""MCP Google Ads server — live reads over the EXISTING OAuth connection.

Nothing here reimplements Google OAuth or credential storage:

  - the access token is refreshed server-side from the stored, encrypted
    refresh token using the existing provider + settings
  - ``requires_integration="google_ads"`` means policy refuses the call
    unless a verified connection row exists for THIS merchant
  - no OAuth client secret ever appears in a tool argument, a tool result,
    a log line or an audit payload

Campaign creation stays PAUSED and remains approval-gated + gated on
``EXECUTION_ENABLED``, delegating to the existing approved-action executor.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.integrations.mcp.errors import ApprovalRequiredError, ProviderCallError
from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.servers.base import ok, provider_error

MCP_SERVER = "google_ads"

TOOL_LIST = "marketing.google_ads.list_campaigns"
TOOL_PERFORMANCE = "marketing.google_ads.get_campaign_performance"
TOOL_ACCOUNTS = "marketing.google_ads.list_accessible_customers"
TOOL_CREATE = "marketing.google_ads.create_campaign"


def _campaign_payload(
    context: Any, db: Session, merchant_id: uuid.UUID
) -> dict[str, Any]:
    """Live Google Ads read via the EXISTING integration tool.

    Policy has already refused the call unless a verified connection row
    exists for this merchant, so the payload is either live data or an
    honest error the agent can report. An error-shaped payload is raised as
    a classified MCP failure so it can never be recorded as a success.
    """
    from backend.app.integrations.mcp.servers.base import (
        legacy_call,
        unwrap_provider_payload,
    )

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    payload = legacy_call(ctx, "get_google_ads_campaigns")
    return unwrap_provider_payload(payload, tool=TOOL_LIST, provider="google_ads")


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> Any:
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _list_campaigns(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    return _campaign_payload(context, db, merchant_id)


def _campaign_performance(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Campaign performance from the same live GAQL read, metric-shaped."""
    payload = _campaign_payload(context, db, merchant_id)
    if not payload.get("connected"):
        return payload
    campaigns = payload.get("campaigns") or []
    return {
        "connected": True,
        "provider": "google_ads",
        "account": payload.get("account"),
        "performance": [
            {
                "campaign_id": c.get("id"),
                "name": c.get("name"),
                "status": c.get("status"),
                "impressions": c.get("impressions"),
                "clicks": c.get("clicks"),
                "cost": c.get("cost"),
            }
            for c in campaigns
        ],
        "campaign_count": len(campaigns),
        "note": "Live metrics from the Google Ads API.",
    }


def _accessible_customers(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Accessible customer accounts for the connected Google Ads login."""
    from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "google_ads")
    if row is None:  # pragma: no cover — policy already refused
        raise ProviderCallError(
            "Google Ads is not connected", provider_code="NOT_CONNECTED",
            tool=TOOL_ACCOUNTS, provider="google_ads",
        )
    creds = svc.decrypt_credentials(row)
    settings = get_settings()
    result = GoogleAdsProvider().verify(
        refresh_token=creds.get("refresh_token", ""),
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        developer_token=creds.get("developer_token") or settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        customer_id=(row.connection_metadata or {}).get("customer_id"),
        api_version=settings.GOOGLE_ADS_API_VERSION,
    )
    if not ok(result):
        raise provider_error(result, tool=TOOL_ACCOUNTS, provider="google_ads")
    return {
        "connected": True,
        "provider": "google_ads",
        "account": result.account,
        "accessible_customer_ids": result.data.get("accessible_customer_ids", []),
    }


def _create_campaign(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    approved_action_id: Any = None,
    context: Any = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a PAUSED campaign via the existing approval-gated executor.

    Policy has already enforced human approval for THIS merchant and
    ``EXECUTION_ENABLED``. The existing ``CreateAdCampaignExecutor`` remains
    the only code path that calls Google Ads create, and it forces
    ``status=PAUSED``.
    """
    if approved_action_id is None:
        raise ApprovalRequiredError(
            f"{TOOL_CREATE} requires an approved action id",
            tool=TOOL_CREATE,
            provider="google_ads",
        )
    from backend.app.integrations.mcp.servers.base import run_approved_write

    return run_approved_write(
        db,
        approved_action_id,
        tool=TOOL_CREATE,
        provider="google_ads",
        audit_label=f"mcp:{TOOL_CREATE}",
        extra={"campaign_status": "PAUSED"},
    )


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802
    """Declarations for the Google Ads MCP server."""
    return [
        MCPToolSpec(
            name=TOOL_LIST,
            description=(
                "Campaigns from the connected Google Ads account. When the "
                "account is not connected the call is refused rather than "
                "returning invented campaigns."
            ),
            provider="google_ads",
            handler=_list_campaigns,
            phase="research",
            requires_integration="google_ads",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_PERFORMANCE,
            description="Campaign performance metrics from the live Google Ads API.",
            provider="google_ads",
            handler=_campaign_performance,
            phase="research",
            requires_integration="google_ads",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_ACCOUNTS,
            description="Google Ads accounts accessible with the stored authorization.",
            provider="google_ads",
            handler=_accessible_customers,
            phase="research",
            requires_integration="google_ads",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_CREATE,
            description=(
                "Create a PAUSED Google Ads campaign. Requires a human-approved "
                "action and EXECUTION_ENABLED; the campaign is never created "
                "active."
            ),
            provider="google_ads",
            handler=_create_campaign,
            phase="execution",
            read_only=False,
            external_write=True,
            requires_approval=True,
            requires_execution_enabled=True,
            requires_integration="google_ads",
            risk_level="critical",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
    ]


ALIASES: dict[str, str] = {
    "get_google_ads_campaigns": TOOL_LIST,
}


__all__ = ["ALIASES", "MCP_SERVER", "TOOLS"]