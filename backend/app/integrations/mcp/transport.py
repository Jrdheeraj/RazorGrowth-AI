"""MCP transport seam — where a real protocol boundary will slot in.

Today the client invokes handlers in-process (``InProcessTransport``):
the server-side callable is a Python function receiving the trusted
``MCPExecutionContext``. That is the reusable MCP foundation, NOT a
wire-protocol implementation.

The seam exists so the long-term target can be introduced without
rewriting the client, registry, policy or observability:

    Marketing Agent → MCP client → Streamable HTTP → MCP server
                                             → existing implementation

A ``StreamableHTTPTransport`` will implement the same ``invoke`` contract
over the official MCP SDK; everything above the transport (schema
validation, policy gates, caching, retries, normalized envelopes, records)
stays byte-for-byte identical. Nothing in this module reasons, approves
or reaches a provider — it only moves one already-authorized invocation.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.schemas import MCPToolSpec


@runtime_checkable
class MCPTransport(Protocol):
    """Contract for delivering one authorized tool invocation."""

    def invoke(
        self,
        spec: MCPToolSpec,
        ctx: MCPExecutionContext,
        arguments: dict[str, Any],
        approved_action_id: Any,
    ) -> Any:
        """Run the tool's handler and return its raw (unnormalized) result.

        Implementations must NOT re-run policy — the client has already
        enforced allowlist, tenant, integration, approval and execution
        gates before this is called. Failures raise; the client
        classifies them into the MCP error taxonomy. A non-mapping result
        is returned as-is so ``validate_output`` reports it honestly
        instead of a transport wrapper hiding the bug.
        """
        ...


class InProcessTransport:
    """Default transport: direct in-process handler invocation.

    Used for local development and tests. The handler receives the
    trusted context (DB session + authenticated merchant id) — never
    model-supplied identity — exactly as before the seam existed.
    """

    def invoke(
        self,
        spec: MCPToolSpec,
        ctx: MCPExecutionContext,
        arguments: dict[str, Any],
        approved_action_id: Any,
    ) -> Any:
        return spec.handler(
            db=ctx.db,
            merchant_id=ctx.merchant_id,
            context=ctx,
            approved_action_id=approved_action_id,
            **arguments,
        )


__all__ = ["InProcessTransport", "MCPTransport"]
