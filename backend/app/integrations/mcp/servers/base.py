"""Shared plumbing for MCP tool handlers.

A handler receives keyword-only arguments injected by the client:

    db, merchant_id, context, approved_action_id, arguments

and returns a plain dict. It never receives a model-supplied merchant id —
``merchant_id`` always comes from ``context`` / the authenticated session,
so a tool cannot be pointed at another tenant.

Handlers raise ``MCPError`` subclasses for refusals and
``ProviderCallError`` for provider failures. They NEVER return a fabricated
payload to paper over a missing integration.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import ProviderCallError


def execution_enabled() -> bool:
    """Read the global execution switch (single source of truth)."""
    return bool(get_settings().EXECUTION_ENABLED)


def run_approved_write(
    db: Session,
    approved_action_id: Any,
    *,
    tool: str,
    provider: str,
    audit_label: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an approved action through the EXISTING action pipeline.

    This is the ONLY write path MCP uses. It delegates to
    ``action_service.execute_action``, which re-checks the action state,
    re-evaluates the guardrails immediately before the provider call,
    honours ``EXECUTION_ENABLED`` inside each executor, and writes the
    audit events — so MCP adds connectivity, not a parallel write path.

    A refused execution is raised, never returned as a success envelope:
    an approval that was not granted, or an execution switch that is off,
    must surface as a failure rather than as a successful tool call.
    """
    from backend.app.integrations.mcp.errors import (
        MCPError,
        classify_executor_error,
    )
    from backend.app.services import action_service

    result = action_service.execute_action(
        db, approved_action_id, actor=audit_label
    )
    payload: dict[str, Any] = {
        "executed": bool(result.success),
        "provider": provider,
        "result": result.result_metadata or {},
        "approval_gated": True,
        "executed_via": "action_service.execute_action",
    }
    if extra:
        payload.update(extra)
    if not result.success:
        raise MCPError(
            result.error or f"{tool}: execution was refused",
            code=classify_executor_error(result.error),
            tool=tool,
            provider=provider,
        )
    return payload


def connected_credentials(
    db: Session,
    merchant_id: uuid.UUID,
    provider: str,
) -> dict[str, Any] | None:
    """Resolve stored credentials server-side for a CONNECTED provider.

    Returns None when the provider is not connected for THIS merchant, or
    when the stored blob cannot be decrypted. Credentials are returned to
    the provider adapter only — never to the model, never into a result,
    never into a log line.
    """
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, provider)
    if row is None:
        return None
    try:
        return svc.decrypt_credentials(row)
    except Exception:
        return None


def connection_metadata(
    db: Session, merchant_id: uuid.UUID, provider: str
) -> dict[str, Any]:
    """Non-secret connection metadata (account ids/names) or {}."""
    from backend.app.services import integration_service as svc

    row = svc.connected_row(db, merchant_id, provider)
    return dict((row.connection_metadata if row else {}) or {})


def provider_error(
    result: Any, *, tool: str, provider: str
) -> ProviderCallError:
    """Convert a failed ``ProviderResult`` into a classified MCP error.

    Centralised so every provider read/write reports failures identically
    and no adapter can accidentally turn a failure into a success.
    """
    return ProviderCallError(
        (getattr(result, "message", None) or "provider call failed"),
        provider_code=getattr(result, "error_code", None),
        tool=tool,
        provider=provider,
    )


def ok(result: Any) -> bool:
    return bool(getattr(result, "ok", False))


def unwrap_provider_payload(
    payload: dict[str, Any], *, tool: str, provider: str
) -> dict[str, Any]:
    """Turn an existing tool's error-SHAPED payload into a real MCP failure.

    The pre-existing integration tools report a provider failure by
    returning a normal dict with ``status="error"`` plus ``error_code`` /
    ``message`` rather than by raising. That is honest for their own
    consumers, but through MCP it would be recorded as a green
    ``status="success"`` call, emit a success activity event and leave the
    provider unmarked as degraded — i.e. a failed provider read presented to
    the model and the dashboard as a success.

    So the MCP adapter converts the shape back into an exception. The
    payload itself is unchanged, and nothing is invented either way: a
    failure is reported as a classified failure.
    """
    if not isinstance(payload, dict):
        return payload
    status = str(payload.get("status") or "").lower()
    if status == "error" or payload.get("error_code"):
        raise ProviderCallError(
            payload.get("message") or f"{tool}: provider call failed",
            provider_code=payload.get("error_code"),
            tool=tool,
            provider=provider,
            details={"provider_status": status} if status else None,
        )
    return payload


def legacy_call(
    ctx: MCPExecutionContext,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke an EXISTING MarketingAGI tool through its own registry.

    This is the migration seam required by the brief: the existing tool
    stays the single implementation of the business logic and keeps its
    allowlist, while MCP owns the standardized contract (name, schema,
    policy, caching, retries, normalization) above it. The ToolContext is
    rebuilt bound to THIS context's session and merchant, so the legacy
    tool's own ``merchant_id``-filtered queries apply unchanged.

    Defence in depth: tenant/credential/guardrail argument keys are
    stripped here too, so even a caller that skips the MCP client's
    sanitizer cannot inject ``merchant_id`` into a legacy tool.
    """
    from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
    from backend.app.agents.marketing_agi.tools.registry import (
        ToolContext,
        get_registry,
    )
    from backend.app.integrations.mcp.schemas import (
        FORBIDDEN_ARG_KEYS,
        GUARDRAIL_ARG_KEYS,
    )

    # Idempotent: ensures the underlying tool implementations are
    # registered even when MCP is driven without constructing the agent.
    register_all_tools()
    clean = {
        k: v
        for k, v in dict(arguments or {}).items()
        if k not in FORBIDDEN_ARG_KEYS and k not in GUARDRAIL_ARG_KEYS
    }
    tool_ctx = ToolContext(
        db=ctx.db,
        merchant_id=ctx.merchant_id,
        llm=None,
        embedding_provider=getattr(ctx, "embedding_provider", None),
    )
    call = get_registry().call(tool_ctx, tool_name, clean)
    return call.get("result", {})


__all__ = [
    "MCPExecutionContext",
    "connected_credentials",
    "connection_metadata",
    "execution_enabled",
    "legacy_call",
    "ok",
    "provider_error",
    "unwrap_provider_payload",
]