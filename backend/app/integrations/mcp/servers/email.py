"""MCP email server â€” Resend connection reads plus the approval-gated send.

Reads reuse the platform's own campaign store and the REAL Resend
connection state (never fabricated). Sending is exposed as an MCP tool but
is a WRITE: it requires a human-approved action AND ``EXECUTION_ENABLED``,
and it delegates to the existing approval-gated executor
(services/action_executor.py) rather than re-implementing a send path.

The LLM therefore cannot send an email by selecting a tool. The flow stays:

    LLM selects marketing.email.send_campaign
      â†’ draft created + verified
      â†’ approval requested
      â†’ human approves
      â†’ MCP tool invoked WITH the approved action id
      â†’ existing executor â†’ Resend â†’ audit
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.errors import ApprovalRequiredError
from backend.app.integrations.mcp.schemas import MCPToolSpec

MCP_SERVER = "email"

#: The approval-gated external write. Named here so the approved-execution
#: bridge can address it without importing this module's internals.
TOOL_SEND = "marketing.email.send_campaign"


def _campaigns(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Email campaigns recorded on the platform + live Resend state.

    Delegates to the existing integration tool, so there is one
    implementation of the platform-campaign read.
    """
    from backend.app.integrations.mcp.servers.base import legacy_call

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    return legacy_call(ctx, "get_email_campaigns")


def _performance(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Honest measured performance: opens/clicks remain unavailable."""
    from backend.app.integrations.mcp.servers.base import legacy_call

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    return legacy_call(ctx, "get_email_campaign_performance")


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> Any:
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _connection(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Sender / connection status â€” safe identity only, never the API key."""
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, "resend")
    if row is None:
        return {
            "connected": False,
            "provider": "resend",
            "status": "requires_integration",
            "note": (
                "No Resend connection is verified for this workspace. "
                "Connect it from the Marketing Agent integration hub."
            ),
        }
    meta = dict(row.connection_metadata or {})
    return {
        "connected": True,
        "provider": "resend",
        "status": "connected",
        "account_id": row.account_id,
        "account_name": row.account_name,
        "from_email": meta.get("from_email"),
        "from_name": meta.get("from_name"),
        "domain_count": meta.get("domain_count", 0),
        "last_verified_at": (
            row.last_verified_at.isoformat() if row.last_verified_at else None
        ),
        "note": "Connected. Sending still requires human approval.",
    }


def _draft_campaign(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Persist a complete campaign draft on THIS platform.

    This is a LOCAL write: it creates a DRAFT row and nothing external. The
    resulting draft is still inert â€” sending requires a verified Resend
    connection AND a human-approved action through the action pipeline.

    ``run_id`` is taken from the execution context, never from the model's
    arguments: ``marketing_agi_campaigns.run_id`` is a foreign key into a
    specific merchant's run, so a model-supplied id would let one tenant
    attach a campaign row to another tenant's run.
    """
    from backend.app.integrations.mcp.servers.base import legacy_call

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    kwargs.pop("run_id", None)
    run_id = getattr(ctx, "run_id", None)
    if run_id:
        try:
            kwargs["run_id"] = uuid.UUID(str(run_id))
        except (ValueError, AttributeError, TypeError):
            kwargs.pop("run_id", None)
    return legacy_call(ctx, "create_email_campaign_draft", kwargs)


def _send_campaign(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    approved_action_id: Any = None,
    context: Any = None,
    **_: Any,
) -> dict[str, Any]:
    """Send an approved campaign through the EXISTING executor pipeline.

    Policy has already guaranteed (a) a human-approved action for THIS
    merchant and (b) EXECUTION_ENABLED. This handler does not talk to Resend
    itself â€” it calls action_service.execute_action, which re-runs the
    idempotency checks and the pre-execution guardrail immediately before
    the provider call. Approval therefore cannot be bypassed by reaching
    this tool.
    """
    if approved_action_id is None:
        raise ApprovalRequiredError(
            "marketing.email.send_campaign requires an approved action id",
            tool="marketing.email.send_campaign",
            provider="resend",
        )
    from backend.app.integrations.mcp.servers.base import run_approved_write

    return run_approved_write(
        db,
        approved_action_id,
        tool="marketing.email.send_campaign",
        provider="resend",
        audit_label="mcp:marketing.email.send_campaign",
    )


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802
    """Declarations for the email (Resend) MCP server."""
    return [
        MCPToolSpec(
            name="marketing.email.get_campaigns",
            description=(
                "Email campaigns recorded on this workspace with the real "
                "Resend connection state."
            ),
            provider="resend",
            handler=_campaigns,
            phase="research",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.email.get_campaign_performance",
            description=(
                "Measured outcomes for recorded email campaigns. Opens, "
                "clicks and bounces are reported as unavailable, never invented."
            ),
            provider="resend",
            handler=_performance,
            phase="research",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.email.get_connection",
            description=(
                "Resend connection and sender identity for this workspace. "
                "Returns safe identity only â€” never the API key."
            ),
            provider="resend",
            handler=_connection,
            phase="observe",
            requires_integration="resend",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.email.draft_campaign",
            description=(
                "Persist a complete email campaign draft (audience, message, "
                "variants, CTA, timing, expected impact) on this platform. "
                "The draft is inert: sending still requires human approval."
            ),
            provider="resend",
            handler=_draft_campaign,
            phase="campaign_prep",
            read_only=False,
            external_write=False,
            risk_level="low",
            input_schema=_schema(
                {
                    "campaign_key": {"type": "string", "minLength": 1, "maxLength": 140},
                    "workflow": {"type": "string", "minLength": 1, "maxLength": 60},
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "objective": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "audience": {"type": "object"},
                    "audience_count": {"type": "integer", "minimum": 0, "maximum": 1000000},
                    "content": {"type": "object"},
                    "expected_impact": {"type": "object"},
                    "success_metric": {"type": "string", "maxLength": 255},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                required=[
                    "campaign_key",
                    "workflow",
                    "name",
                    "objective",
                    "audience",
                    "audience_count",
                    "content",
                    "expected_impact",
                    "success_metric",
                    "evidence_refs",
                ],
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_SEND,
            description=(
                "Send a prepared email campaign through Resend. Requires a "
                "human-approved action and EXECUTION_ENABLED; without them "
                "the call is refused."
            ),
            provider="resend",
            handler=_send_campaign,
            phase="execution",
            read_only=False,
            external_write=True,
            requires_approval=True,
            requires_execution_enabled=True,
            requires_integration="resend",
            risk_level="critical",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
    ]


ALIASES: dict[str, str] = {
    "get_email_campaigns": "marketing.email.get_campaigns",
    "get_email_campaign_performance": "marketing.email.get_campaign_performance",
    "create_email_campaign_draft": "marketing.email.draft_campaign",
}


__all__ = ["ALIASES", "MCP_SERVER", "TOOL_SEND", "TOOLS"]