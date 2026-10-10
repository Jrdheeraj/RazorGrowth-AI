"""MCP bridge for the existing MarketingAGI tool registry.

Two jobs, both additive — the existing ``MarketingToolRegistry`` keeps
working exactly as before:

  1. ``resolve`` maps a legacy MarketingAGI tool name (or a workflow's
     preferred tool name) onto its canonical MCP tool, so the agent can
     migrate per-call without a big-bang rewrite.
  2. ``mcp_invoke`` runs a tool through the MCP client and unwraps the
     normalized envelope, returning the tool's own data payload so every
     existing consumer (audience builder, verifier, RAG, state) keeps
     seeing the shape it already expects.

Nothing here changes tool semantics: MCP calls the SAME implementations.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from backend.app.integrations.mcp.client import MCPClient
from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import MCPError
from backend.app.integrations.mcp.registry import get_mcp_registry

log = logging.getLogger(__name__)

#: Workflow investigation tools that have NO MCP equivalent (they are
#: agent-local orchestration, not data access).
NON_MCP_AGENT_TOOLS: frozenset[str] = frozenset({"verifier", "campaign_strategy"})


def resolve(tool_name: str) -> str | None:
    """Canonical MCP tool name for a legacy tool name, or None.

    ``None`` means "not an MCP-backed tool" — the caller keeps its existing
    behaviour for it.
    """
    registry = get_mcp_registry()
    if registry.has(tool_name):
        return registry.spec(tool_name).name
    return registry.mcp_name_for(tool_name)


def is_mcp_tool(tool_name: str) -> bool:
    return resolve(tool_name) is not None


def registered_names() -> set[str]:
    """Every name the MCP registry will accept: canonical + legacy aliases.

    The agent uses this to build its dispatch allowlist so a model that
    picks a dotted MCP name from a phase catalog is accepted exactly like
    a legacy name — while still being refused for anything unregistered.
    """
    registry = get_mcp_registry()
    return set(registry.names()) | set(registry.legacy_names())


def mcp_invoke(
    client: MCPClient,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    approved_action_id: Any = None,
) -> dict[str, Any] | None:
    """Run a legacy tool name through MCP and return its unwrapped data.

    Returns ``None`` when the tool is not MCP-backed, letting the caller
    fall back to the legacy registry. Raises ``MCPError`` on a real MCP
    failure so the agent records an honest gap instead of continuing with
    an invented result.
    """
    mcp_name = resolve(tool_name)
    if mcp_name is None:
        return None
    envelope = client.call(
        mcp_name, arguments, approved_action_id=approved_action_id
    )
    if envelope.get("status") != "success":
        error = envelope.get("error") or {}
        raise MCPError(
            error.get("message") or f"{mcp_name} failed",
            code=error.get("code", "PROVIDER_ERROR"),
            tool=mcp_name,
            provider=(envelope.get("metadata") or {}).get("provider"),
        )
    return envelope.get("data") or {}


def build_client(
    db: Any,
    merchant_id: Any,
    *,
    run_id: str | None = None,
    embedding_provider: Any = None,
    execution_enabled: bool | None = None,
    on_call: Any = None,
    client: MCPClient | None = None,
    max_retries: int | None = None,
    sleep: Callable[[float], None] | None = None,
    transport: Any = None,
) -> MCPClient:
    """Construct an MCP client bound to this authenticated merchant.

    The execution switch is snapshotted from settings at construction so a
    mid-run environment change cannot turn a withheld write into a real one.

    ``client`` reuses an existing client's per-run state (its read cache
    and degraded-provider set are SHARED by reference) while binding a
    fresh DB session onto a copied context. That is how the parallel
    observation path fans out: one shared cache, one session per worker —
    without ever mutating the parent client's context (a shared mutation
    would race across workers and leave the parent pointing at a closed
    session).
    """
    from dataclasses import replace as _replace

    from backend.app.core.config import get_settings

    if execution_enabled is None:
        execution_enabled = bool(get_settings().EXECUTION_ENABLED)
    if client is not None:
        # Shallow copy: cache/degraded sets are shared (same object
        # references), db/merchant_id are rebound on the copy only.
        #
        # The merchant may NOT change. A fan-out worker exists to give each
        # thread its own DB session for the SAME authenticated merchant; if
        # a caller ever asked for a different merchant, the shared cache
        # would serve the first tenant's rows to the second. The cache key
        # is tenant-bound too, so this is defence in depth — but a loud
        # failure beats a silent cross-tenant read.
        if client.context.merchant_id != merchant_id:
            from backend.app.integrations.mcp.errors import TenantScopeError

            raise TenantScopeError(
                "a worker MCP client cannot change the authenticated merchant",
                tool="build_client",
            )
        ctx = _replace(
            client.context,
            db=db,
            merchant_id=merchant_id,
            embedding_provider=embedding_provider or client.context.embedding_provider,
        )
        return MCPClient(
            ctx,
            max_retries=client.max_retries if max_retries is None else max_retries,
            sleep=sleep or client.sleep,
            on_call=on_call,
            # Workers inherit the parent's transport so a future Streamable
            # HTTP boundary applies to every fan-out call too.
            transport=transport if transport is not None else client.transport,
        )
    ctx = MCPExecutionContext(
        db=db,
        merchant_id=merchant_id,
        run_id=run_id,
        execution_enabled=bool(execution_enabled),
    )
    # The embedding provider is not part of the tenant context; it is
    # attached here so the knowledge/memory handlers can reuse the run's
    # already-configured retriever instead of building a second one.
    ctx.embedding_provider = embedding_provider  # type: ignore[attr-defined]
    kwargs: dict[str, Any] = {"on_call": on_call}
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if sleep is not None:
        kwargs["sleep"] = sleep
    if transport is not None:
        kwargs["transport"] = transport
    return MCPClient(ctx, **kwargs)


__all__ = [
    "NON_MCP_AGENT_TOOLS",
    "build_client",
    "is_mcp_tool",
    "mcp_invoke",
    "registered_names",
    "resolve",
]