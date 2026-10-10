"""MCP execution context — the authenticated tenant scope for one run.

The context is built ONCE from the backend-authenticated merchant (the
same value the MarketingAGI worker binds its DB session to) and is then
read-only. Every tool invocation reads merchant identity from here, never
from tool arguments, so

    merchant A → MCP → merchant B credentials

is structurally impossible: the handler receives no merchant argument and
resolves credentials through ``integration_service`` with ``ctx.merchant_id``.

The context also carries a per-run read cache (never shared across runs or
tenants) and the degraded-provider set used when a provider fails.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class MCPExecutionContext:
    """Immutable tenant scope + per-run caches for MCP invocations."""

    db: Session
    merchant_id: uuid.UUID
    run_id: str | None = None
    #: Read-only result cache for THIS run only. Cleared by the agent at
    #: the start of every run; keyed by (tool, stable-args).
    cache: dict[str, Any] = field(default_factory=dict)
    #: Providers that failed during this run — surfaced to the agent so it
    #: stops hammering a broken provider and says so honestly.
    degraded_providers: set[str] = field(default_factory=set)
    #: Providers with no verified connection for this workspace.
    disconnected_providers: set[str] = field(default_factory=set)
    #: Execution switch, snapshotted so a mid-run env change cannot turn a
    #: withheld write into a real one.
    execution_enabled: bool = False
    #: Embedding provider for the knowledge/memory MCP tools. Not tenant
    #: data — attached by the bridge so those handlers reuse the run's
    #: already-configured retriever instead of building a second one.
    embedding_provider: Any = None

    def cache_key(self, tool: str, arguments: dict[str, Any]) -> str:
        """Cache identity for one read-only query.

        The merchant id is part of the key. The cache is per-run and
        per-context today, so this is belt-and-braces — but the bridge
        deliberately shares one cache object across a fan-out, so binding
        the tenant into the key means a future caller that reuses a
        client's cache for a second merchant serves a MISS (safe) instead
        of another tenant's rows (catastrophic).

        The fallback keeps argument VALUES in the key. A key-name-only
        fallback would make two different queries collide onto one cached
        payload, which is a silent wrong answer rather than a cache miss.
        """
        import json

        body = ""
        try:
            body = json.dumps(arguments, sort_keys=True, default=repr)
        except Exception:
            # sort_keys compares keys of mixed types; repr of the pairs is
            # order-independent and never drops a value.
            body = repr(sorted((str(k), repr(v)) for k, v in (arguments or {}).items()))
        return f"{self.merchant_id}|{tool}|{body}"

    def mark_degraded(self, provider: str) -> None:
        if provider:
            self.degraded_providers.add(provider)

    def is_degraded(self, provider: str) -> bool:
        return provider in self.degraded_providers

    def cache_stats(self) -> dict[str, int]:
        return {"cache_size": len(self.cache)}


__all__ = ["MCPExecutionContext"]