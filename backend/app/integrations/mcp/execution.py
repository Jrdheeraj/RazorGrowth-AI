"""Approved external writes dispatched THROUGH the MCP tool layer.

This is where the approval boundary meets the connectivity layer. The flow
is single-path by design:

    LLM selects a write tool
        -> draft created
        -> verification
        -> approval requested
        -> HUMAN approves
        -> MCP tool invocation   <-- this module, the ONLY entry
        -> policy: tenant -> integration -> approval -> EXECUTION_ENABLED
        -> existing action executor -> provider
        -> audit

There is deliberately NO second execution path. An approved marketing
external write that MCP cannot serve is REFUSED by MCP
(``INTEGRATION_NOT_CONNECTED`` / ``EXECUTION_DISABLED``) and performs no
external execution. Routing it around MCP to a legacy executor would mean
the connectivity layer could be skipped by a disconnected integration,
which is exactly what this module exists to prevent.

MCP does not re-implement any provider logic: the write handler calls
``action_service.execute_action``, which still owns the action state
machine, the production kill-switch, the double guardrail re-evaluation
and the audit events. MCP contributes the standardized contract plus the
gates the model cannot touch:

  - ``approved_action_id`` is threaded from the AUTHENTICATED HTTP request
    (never from a tool argument and never from the model), and MCP policy
    re-verifies that the action belongs to the caller's merchant
  - ``EXECUTION_ENABLED`` and integration availability are evaluated by the
    policy layer before any provider is touched

Action types that are NOT marketing external writes (discounts, payment
retries, opportunity generation) are not claimed here and keep their
existing execution path. That is an honest scope boundary, not a second
write path: no marketing external write can be executed without passing
through this module.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.errors import (
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    MCPError,
)
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.integrations.mcp.servers import email as email_server
from backend.app.integrations.mcp.servers import google_ads as google_ads_server
from backend.app.integrations.mcp.servers import instagram as instagram_server
from backend.app.integrations.mcp.servers import meta_ads as meta_ads_server

#: Ad-platform actions can target either connected provider. The choice is
#: made from the action's own stored payload (which the agent prepared and
#: a human approved), never from a model-supplied tool name.
_AD_PROVIDER_TOOL = {
    "google_ads": google_ads_server.TOOL_CREATE,
    "meta_ads": meta_ads_server.TOOL_CREATE,
}

#: Action types whose execution is a MARKETING EXTERNAL WRITE. Every one of
#: them MUST be dispatched through MCP - there is no legacy bypass. A type
#: outside this set is simply not a marketing external write.
MARKETING_EXTERNAL_WRITE_TYPES: frozenset[str] = frozenset(
    {"send_campaign", "publish_social_post", "create_ad_campaign"}
)


def mcp_tool_for_action(action: Any) -> str | None:
    """Canonical MCP tool that performs this approved action, or None.

    ``None`` means "not an MCP-backed external write" — the caller keeps
    its existing execution path for it. It is never returned for a type in
    ``MARKETING_EXTERNAL_WRITE_TYPES``; an unresolvable ad platform raises
    instead, so a marketing write can never fall through to a legacy path.
    """
    action_type = getattr(action, "action_type", None)
    value = getattr(action_type, "value", action_type)
    if value == "send_campaign":
        return email_server.TOOL_SEND
    if value == "publish_social_post":
        return instagram_server.TOOL_PUBLISH
    if value == "create_ad_campaign":
        payload = getattr(action, "input_payload", None) or {}
        provider = ""
        if isinstance(payload, dict):
            provider = str(
                payload.get("platform") or payload.get("provider") or ""
            ).strip().lower()
        tool = _AD_PROVIDER_TOOL.get(provider)
        if tool is None:
            # Refuse rather than fall back: an unknown ad platform must not
            # reach a provider through any other route.
            raise MCPError(
                "create_ad_campaign targets no known ad platform "
                f"({provider or 'none declared'}). Refusing execution.",
                code=VALIDATION_ERROR,
                tool="mcp.execution",
                provider="ad_platform",
            )
        return tool
    return None


def is_marketing_external_write(action: Any) -> bool:
    """True when this action must be executed through MCP."""
    action_type = getattr(action, "action_type", None)
    value = getattr(action_type, "value", action_type)
    return value in MARKETING_EXTERNAL_WRITE_TYPES


def execute_approved_action(
    db: Session,
    merchant_id: uuid.UUID,
    action_id: uuid.UUID,
    *,
    actor: str = "mcp",
) -> Any:
    """Execute one approved action through its MCP tool.

    Returns ``None`` only when the action is genuinely not an MCP-managed
    write, so the caller keeps its existing path. For every marketing
    external write this ALWAYS returns a result: a success envelope from
    the existing executor, or an honest refusal from MCP policy. The
    merchant's connection state is NOT consulted here — policy decides that
    — so there is no way to reach a provider by being disconnected.
    """
    from backend.app.models.enums import AgentActionStatus
    from backend.app.services.action_service import get_action
    from backend.app.services.action_executor import ExecutorResult

    action = get_action(db, action_id)
    if action is None:
        return None
    # Tenant check BEFORE anything else: an approved action belonging to
    # another workspace must never be executable from this request.
    if action.merchant_id != merchant_id:
        return None
    # Only a genuinely APPROVED action is claimed here. Every other state
    # (requested, executing, completed, rejected, failed) falls through to
    # the existing ``action_service`` path, which owns the state machine and
    # must keep producing its own canonical refusals - INVALID_ACTION_STATE,
    # idempotent no-op, tenant denial. This is not a write bypass: an
    # unapproved action performs no external write on either path, because
    # ``execute_action`` refuses it before the executor runs.
    if getattr(action.status, "value", action.status) != AgentActionStatus.approved.value:
        return None
    if not is_marketing_external_write(action):
        return None

    tool = mcp_tool_for_action(action)
    if tool is None:  # pragma: no cover - guarded by is_marketing_external_write
        return None
    # Fail loudly if a claimed write is not actually registered - a missing
    # registration must never become a silent legacy execution.
    get_mcp_registry().spec(tool)

    client = mcp_bridge.build_client(db, merchant_id, on_call=None)
    envelope = client.call(tool, None, approved_action_id=action_id)
    if envelope.get("status") == "success":
        data = dict(envelope.get("data") or {})
        metadata = dict(data.pop("result", None) or {})
        metadata["mcp_tool"] = tool
        metadata["mcp_provider"] = data.get("provider")
        metadata["approval_gated"] = True
        metadata["executed_via"] = "mcp_tool_layer"
        return ExecutorResult(success=True, result_metadata=metadata)

    error = dict(envelope.get("error") or {})
    return ExecutorResult(
        success=False,
        # The message is already credential-scrubbed by the MCP layer.
        error=(
            f"{error.get('code', INTERNAL_ERROR)}: "
            f"{error.get('message', 'execution failed')}"
        ),
        result_metadata={
            "mcp_tool": tool,
            "mcp_error_code": error.get("code"),
            "external_execution_performed": False,
        },
    )


__all__ = [
    "MARKETING_EXTERNAL_WRITE_TYPES",
    "execute_approved_action",
    "is_marketing_external_write",
    "mcp_tool_for_action",
]