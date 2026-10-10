"""MCP Instagram server — connected-account read plus approval-gated publish.

The Meta access token is resolved server-side from the encrypted
connection row; no credential is ever part of a tool argument or result.
Publishing is exposed as a WRITE and delegates to the existing
approval-gated ``publish_social_post`` executor, so it can only run after a
human-approved action and with ``EXECUTION_ENABLED``.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.errors import ApprovalRequiredError
from backend.app.integrations.mcp.schemas import MCPToolSpec

MCP_SERVER = "instagram"

TOOL_ACCOUNT = "marketing.instagram.get_account"
TOOL_PUBLISH = "marketing.instagram.publish"


def _account(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Verified Instagram business identity — honest when disconnected.

    Delegates to the existing social tool, so the Graph API call, the
    honest "no account" payload and the unavailability notes stay in one
    place. An error-shaped payload is raised as a classified MCP failure so
    a failed Graph call is never recorded as a successful tool call.
    """
    from backend.app.integrations.mcp.servers.base import (
        legacy_call,
        unwrap_provider_payload,
    )

    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    payload = legacy_call(ctx, "get_social_performance")
    return unwrap_provider_payload(payload, tool=TOOL_ACCOUNT, provider="instagram")


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> Any:
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _publish(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    approved_action_id: Any = None,
    context: Any = None,
    **_: Any,
) -> dict[str, Any]:
    """Publish an approved post through the existing executor pipeline."""
    if approved_action_id is None:
        raise ApprovalRequiredError(
            f"{TOOL_PUBLISH} requires an approved action id",
            tool=TOOL_PUBLISH,
            provider="instagram",
        )
    from backend.app.integrations.mcp.servers.base import run_approved_write

    return run_approved_write(
        db,
        approved_action_id,
        tool=TOOL_PUBLISH,
        provider="instagram",
        audit_label=f"mcp:{TOOL_PUBLISH}",
    )


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802
    """Declarations for the Instagram MCP server."""
    return [
        MCPToolSpec(
            name=TOOL_ACCOUNT,
            description=(
                "Verified Instagram business identity for the connected "
                "account. Engagement metrics are reported as unavailable "
                "rather than invented."
            ),
            provider="instagram",
            handler=_account,
            phase="research",
            requires_integration="instagram",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name=TOOL_PUBLISH,
            description=(
                "Publish an approved post. Requires a human-approved action "
                "and EXECUTION_ENABLED."
            ),
            provider="instagram",
            handler=_publish,
            phase="execution",
            read_only=False,
            external_write=True,
            requires_approval=True,
            requires_execution_enabled=True,
            requires_integration="instagram",
            risk_level="critical",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
    ]


ALIASES: dict[str, str] = {
    "get_social_performance": TOOL_ACCOUNT,
}


__all__ = ["ALIASES", "MCP_SERVER", "TOOLS"]