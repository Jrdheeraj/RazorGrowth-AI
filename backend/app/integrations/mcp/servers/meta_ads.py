"""MCP Meta Ads server — live reads over the EXISTING Meta OAuth connection.

No second Meta authentication mechanism is introduced: the stored,
encrypted access token is resolved server-side through
``integration_service`` and handed straight to the existing provider
adapter. Campaign creation stays PAUSED, approval-gated and gated on
``EXECUTION_ENABLED``, delegating to the existing executor.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.integrations.mcp.errors import ApprovalRequiredError
from backend.app.integrations.mcp.schemas import MCPToolSpec

MCP_SERVER = "meta_ads"

TOOL_LIST = "marketing.meta_ads.list_campaigns"
TOOL_INSIGHTS = "marketing.meta_ads.get_insights"
TOOL_CREATE = "marketing.meta_ads.create_campaign"


def _campaign_payload(context: Any, db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Live Meta read via the EXISTING integration tool.

    An error-shaped payload is raised as a classified MCP failure so a
    failed provider read is never recorded as a successful tool call.
    """
    from backend.app.integrations.mcp.servers.base import (
        legacy_call,
        unwrap_provider_payload,
    )

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    payload = legacy_call(ctx, "get_meta_campaigns")
    return unwrap_provider_payload(payload, tool=TOOL_LIST, provider="meta_ads")


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> Any:
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _campaigns(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    return _campaign_payload(context, db, merchant_id)


def _insights(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Last-30-day insights per campaign, from the same live Meta read."""
    payload = _campaign_payload(context, db, merchant_id)
    if not payload.get("connected"):
        return payload
    campaigns = payload.get("campaigns") or []
    return {
        "connected": True,
        "provider": "meta_ads",
        "account": payload.get("account"),
        "date_preset": "last_30d",
        "insights": [
            {
                "campaign_id": c.get("id"),
                "name": c.get("name"),
                "status": c.get("status"),
                "impressions": c.get("impressions"),
                "clicks": c.get("clicks"),
                "spend": c.get("spend"),
            }
            for c in campaigns
        ],
        "note": "Live insights from the Meta Marketing API.",
    }


def _create_campaign(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    approved_action_id: Any = None,
    context: Any = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a PAUSED Meta campaign via the approved-action pipeline."""
    if approved_action_id is None:
        raise ApprovalRequiredError(
            f"{TOOL_CREATE} requires an approved action id",
            tool=TOOL_CREATE,
            provider="meta_ads",
        )
    from backend.app.integrations.mcp.servers.base import run_approved_write

    return run_approved_write(
        db,
        approved_action_id,
        tool=TOOL_CREATE,
        provider="meta_ads",
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
    """Declarations for the Meta Ads MCP server."""
    return [
        MCPToolSpec(
            name=TOOL_LIST,
            description=(
                "Ad campaigns from the connected Meta Ads account. Refused "
                "when the account is not connected — never fabricated."
            ),
            provider="meta_ads",
            handler=_campaigns,
            phase="research",
            requires_integration="meta_ads",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_INSIGHTS,
            description="Last-30-day campaign insights (impressions, clicks, spend).",
            provider="meta_ads",
            handler=_insights,
            phase="research",
            requires_integration="meta_ads",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_CREATE,
            description=(
                "Create a PAUSED Meta Ads campaign. Requires a human-approved "
                "action and EXECUTION_ENABLED."
            ),
            provider="meta_ads",
            handler=_create_campaign,
            phase="execution",
            read_only=False,
            external_write=True,
            requires_approval=True,
            requires_execution_enabled=True,
            requires_integration="meta_ads",
            risk_level="critical",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
    ]


ALIASES: dict[str, str] = {
    "get_meta_campaigns": TOOL_LIST,
}


__all__ = ["ALIASES", "MCP_SERVER", "TOOLS"]