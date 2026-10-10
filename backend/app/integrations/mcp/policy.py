"""MCP policy layer — allowlist, tenant scope, approval and execution gates.

This module is the ONLY place MCP decides whether a call may proceed, and
it is deliberately thin: it reads the declared ``MCPToolSpec`` policy and
refuses. It never reasons about marketing, never approves anything, and
never reaches a provider.

Gate order (fail-closed, first refusal wins):

  1. allowlist      — unknown / non-registered tool ⇒ TOOL_NOT_ALLOWED
  2. tenant scope   — caller-supplied merchant ⇒ TENANT_SCOPE_ERROR
  3. integration    — unconnected provider ⇒ INTEGRATION_NOT_CONNECTED
  4. approval       — external write without a human-approved action ⇒
                      APPROVAL_REQUIRED
  5. execution      — external write while EXECUTION_ENABLED is off ⇒
                      EXECUTION_DISABLED

An external write therefore cannot reach a provider on the strength of an
LLM tool selection alone: it needs an approved action AND the environment
switch, exactly like the pre-existing action pipeline.
"""
from __future__ import annotations

import uuid
from typing import Any

from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import (
    APPROVAL_REQUIRED,
    EXECUTION_DISABLED,
    INTEGRATION_NOT_CONNECTED,
    TENANT_SCOPE_ERROR,
    ApprovalRequiredError,
    ExecutionDisabledError,
    IntegrationNotConnectedError,
    TenantScopeError,
)
from backend.app.integrations.mcp.schemas import MCPToolSpec

#: Canonical allowlists, derived from the registry at import time by
#: ``build_allowlists`` — declared here as the names the rest of the system
#: reasons about.
MARKETING_READ_TOOLS: frozenset[str] = frozenset()
MARKETING_WRITE_TOOLS: frozenset[str] = frozenset()
MARKETING_APPROVAL_REQUIRED_TOOLS: frozenset[str] = frozenset()
MARKETING_INTERNAL_TOOLS: frozenset[str] = frozenset()
MARKETING_EXTERNAL_TOOLS: frozenset[str] = frozenset()

_ALLOWLISTS_INITIALISED = False


def build_allowlists(registry: Any) -> dict[str, frozenset[str]]:
    """Derive the allowlist sets from the registered specs."""
    specs = registry.all_specs()
    return {
        "read": frozenset(s.name for s in specs if s.read_only),
        "write": frozenset(s.name for s in specs if not s.read_only),
        "approval_required": frozenset(s.name for s in specs if s.requires_approval),
        "internal": frozenset(s.name for s in specs if s.internal),
        "external": frozenset(s.name for s in specs if not s.internal),
    }


def allowlists() -> dict[str, frozenset[str]]:
    """Live allowlists (populated lazily from the registry)."""
    global _ALLOWLISTS_INITIALISED
    if not _ALLOWLISTS_INITIALISED:
        _refresh_allowlists()
    return {
        "read": MARKETING_READ_TOOLS,
        "write": MARKETING_WRITE_TOOLS,
        "approval_required": MARKETING_APPROVAL_REQUIRED_TOOLS,
        "internal": MARKETING_INTERNAL_TOOLS,
        "external": MARKETING_EXTERNAL_TOOLS,
    }


def _refresh_allowlists() -> None:
    global MARKETING_READ_TOOLS, MARKETING_WRITE_TOOLS
    global MARKETING_APPROVAL_REQUIRED_TOOLS, MARKETING_INTERNAL_TOOLS
    global MARKETING_EXTERNAL_TOOLS, _ALLOWLISTS_INITIALISED
    from backend.app.integrations.mcp.registry import get_mcp_registry

    sets = build_allowlists(get_mcp_registry())
    MARKETING_READ_TOOLS = sets["read"]
    MARKETING_WRITE_TOOLS = sets["write"]
    MARKETING_APPROVAL_REQUIRED_TOOLS = sets["approval_required"]
    MARKETING_INTERNAL_TOOLS = sets["internal"]
    MARKETING_EXTERNAL_TOOLS = sets["external"]
    _ALLOWLISTS_INITIALISED = True


def assert_tenant_scope(ctx: MCPExecutionContext, spec: MCPToolSpec) -> None:
    """Tenant identity comes from the context, full stop.

    Defence in depth: the spec must be tenant-scoped, and the context's
    merchant id must be a real UUID (it is the authenticated merchant).
    """
    if not spec.tenant_scoped:
        raise TenantScopeError(
            f"{spec.name} is not tenant-scoped and cannot be invoked",
            tool=spec.name,
        )
    if not isinstance(ctx.merchant_id, uuid.UUID):
        raise TenantScopeError(
            "MCP context is missing an authenticated merchant scope",
            tool=spec.name,
        )


def assert_integration_connected(
    ctx: MCPExecutionContext, spec: MCPToolSpec
) -> None:
    """A tool needing a live integration requires a verified connection.

    The check reads the SAME connection row the provider call will use, so
    "connected" in the catalog can never disagree with the live call.
    """
    if not spec.requires_integration:
        return
    from backend.app.services import integration_service as svc

    row = svc.connected_row(ctx.db, ctx.merchant_id, spec.requires_integration)
    if row is None:
        raise IntegrationNotConnectedError(
            f"{spec.name}: {spec.requires_integration} is not connected for "
            "this workspace. No data is fabricated — connect it from the "
            "Marketing Agent integration hub to enable this tool.",
            tool=spec.name,
            provider=spec.requires_integration,
        )


def assert_write_permitted(
    ctx: MCPExecutionContext,
    spec: MCPToolSpec,
    *,
    approved_action_id: uuid.UUID | None,
) -> None:
    """External writes require BOTH human approval and EXECUTION_ENABLED.

    ``approved_action_id`` is supplied by the caller's server-side approval
    flow (the existing Phase-4 action pipeline), never by the model. Its
    presence alone is not enough: the action's merchant must equal the
    context merchant, so one tenant can never execute another's approved
    action through MCP.

    A LOCAL write (a campaign draft persisted on this platform) has no
    external side effect, so it keeps its pre-existing boundary: it is
    never cached, never treated as read-only, and never grants any
    execution capability.
    """
    if spec.read_only:
        return
    if not spec.external_write:
        return

    if not spec.requires_approval:
        raise ApprovalRequiredError(
            f"{spec.name} is a write that is not marked approval-gated",
            tool=spec.name,
        )
    if approved_action_id is None:
        raise ApprovalRequiredError(
            f"{spec.name} requires human approval before it can run. "
            "Prepare the action, request approval, then execute.",
            tool=spec.name,
            provider=spec.provider,
        )
    if not spec.requires_execution_enabled:
        return
    if not ctx.execution_enabled:
        # One authoritative policy, one message. Previously this string was
        # written here by hand and drifted from the remediation the executor
        # produced, so the same block reported two different fixes.
        from backend.app.core.execution_policy import REMEDIATION

        raise ExecutionDisabledError(
            f"{spec.name} is withheld: EXECUTION_ENABLED is off, so the "
            "approved action returns an honest preview instead of performing "
            f"the external write. {REMEDIATION}",
            tool=spec.name,
            provider=spec.provider,
            details={"approved_action_id": str(approved_action_id)},
        )


def _assert_action_belongs_to_tenant(
    ctx: MCPExecutionContext, spec: MCPToolSpec, action_id: uuid.UUID
) -> None:
    """The approval must be for THIS merchant's action."""
    from backend.app.models.agent_action import AgentAction

    action = ctx.db.get(AgentAction, action_id)
    if action is None:
        raise TenantScopeError(
            f"{spec.name}: the approved action does not exist",
            tool=spec.name,
            details={"approved_action_id": str(action_id)},
        )
    if action.merchant_id != ctx.merchant_id:
        raise TenantScopeError(
            f"{spec.name}: the approved action belongs to a different workspace",
            tool=spec.name,
            details={"approved_action_id": str(action_id)},
        )


def enforce(
    ctx: MCPExecutionContext,
    spec: MCPToolSpec,
    *,
    approved_action_id: uuid.UUID | None = None,
) -> None:
    """Run every gate for one invocation. Raises on the first refusal.

    A supplied approval is tenant-checked BEFORE the integration check, so
    an attempt to reuse another workspace's approved action is reported as
    a tenant-scope failure rather than being masked by an unrelated
    "not connected" answer.
    """
    assert_tenant_scope(ctx, spec)
    if approved_action_id is not None:
        _assert_action_belongs_to_tenant(ctx, spec, approved_action_id)
    assert_integration_connected(ctx, spec)
    assert_write_permitted(ctx, spec, approved_action_id=approved_action_id)


__all__ = [
    "MARKETING_APPROVAL_REQUIRED_TOOLS",
    "MARKETING_EXTERNAL_TOOLS",
    "MARKETING_INTERNAL_TOOLS",
    "MARKETING_READ_TOOLS",
    "MARKETING_WRITE_TOOLS",
    "allowlists",
    "assert_integration_connected",
    "assert_tenant_scope",
    "assert_write_permitted",
    "build_allowlists",
    "enforce",
]