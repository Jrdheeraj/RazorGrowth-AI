"""MCP observability ledger — turns tool calls into agent state + events.

The MCP client already records one safe ``MCPToolCallRecord`` per
invocation. The ledger adapts those records into the Marketing Agent's
EXISTING observability surfaces rather than a parallel monitoring system:

  - ``state.mcp_calls``  — durable, tenant-safe rows in run state
  - ``state.tool_calls`` — the dashboard's current tool-activity shape
  - ``MarketingAGIEvent`` rows of type ``mcp_tool_call`` — the Live
    Activity timeline, so an MCP failure shows up honestly next to every
    other real agent event

Nothing recorded here contains prompts, arguments values from forbidden
keys, credential material or raw provider bodies.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from backend.app.integrations.mcp.client import MCPToolCallRecord

log = logging.getLogger(__name__)

#: Failure codes rendered as a warning rather than a neutral error, because
#: they are expected states (an unconnected integration is not a crash).
EXPECTED_CODES: frozenset[str] = frozenset({"INTEGRATION_NOT_CONNECTED"})


class MCPLedger:
    """Collects MCP call records for one run and mirrors them outward."""

    def __init__(self) -> None:
        self.records: list[MCPToolCallRecord] = []
        self._sink: Callable[[MCPToolCallRecord], None] | None = None

    # ── wiring ───────────────────────────────────────────────────────────

    def bind(self, sink: Callable[[MCPToolCallRecord], None]) -> None:
        """Attach the per-run sink (state + event recorder)."""
        self._sink = sink

    def reset(self) -> None:
        self.records.clear()
        self._sink = None

    # ── collection ───────────────────────────────────────────────────────

    def record(self, record: MCPToolCallRecord) -> None:
        """Called by the MCP client after every invocation."""
        self.records.append(record)
        if self._sink is None:
            return
        try:
            self._sink(record)
        except Exception:  # observability must never break a tool call
            log.debug("MCP ledger sink failed", exc_info=True)

    def as_rows(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.records]

    def metrics(self, client: Any) -> dict[str, Any]:
        return client.metrics()


__all__ = ["EXPECTED_CODES", "MCPLedger"]