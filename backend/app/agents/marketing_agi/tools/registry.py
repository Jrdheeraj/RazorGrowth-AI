"""MarketingAGI tool registry — capability-based, allowlisted, tenant-scoped.

Every tool receives (db, merchant_id) at construction and EVERY query it
performs filters by merchant_id in SQL. The registry enforces:

  - an allowlist of registered tool names (unknown tools can never run)
  - a category per tool, surfaced to the reasoning loop for selection
  - read-only marketing data tools + draft/preparation tools only
  - NO tool may approve, reject, execute, or bypass guardrails

Unified integration metadata (Phase 9): every tool declares its provider,
connection requirement, read/write surface and approval requirement in
ONE place. External writes are NEVER executed from tools — write_actions
are executed exclusively through the human-approved action pipeline
(services/action_executor.py); the registry only declares them.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.embeddings.base import BaseEmbeddingProvider


class ToolError(Exception):
    """Raised when a tool call fails or is refused."""


# Tool categories backed by the platform's own database (no external
# provider, no connection needed). Anything else must declare its
# provider explicitly on its ToolSpec.
INTERNAL_CATEGORIES = frozenset(
    {"analytics", "customers", "products", "marketing", "knowledge", "payments"}
)


@dataclass
class ToolSpec:
    name: str
    category: str            # analytics | customers | marketing | knowledge | products | payments | integrations
    description: str
    capabilities: list[str] = field(default_factory=list)
    integration_status: str = "connected"   # connected | draft_only | requires_integration
    # ── Unified integration metadata (single canonical declaration) ──
    provider: str | None = None        # resend | google_ads | meta_ads | instagram | internal | None
    requires_connection: bool = False  # live data needs a verified connection row
    read_only: bool = True             # False only for local draft persistence
    write_actions: list[str] = field(default_factory=list)  # external writes (approval-gated, via actions)
    writes_require_approval: bool = False


class ToolContext:
    """Everything a tool is allowed to touch."""

    def __init__(
        self,
        db: Session,
        merchant_id: uuid.UUID,
        llm: BaseLLMProvider | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.merchant_id = merchant_id
        self.llm = llm
        self.embedding_provider = embedding_provider


class MarketingToolRegistry:
    """Allowlisted registry of MarketingAGI tools."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._factories: dict[str, Callable[[ToolContext], Callable[..., Any]]] = {}

    def register(
        self,
        spec: ToolSpec,
        factory: Callable[[ToolContext], Callable[..., Any]],
    ) -> None:
        if spec.name in self._specs:
            raise ToolError(f"Tool already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._factories[spec.name] = factory

    def spec(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise ToolError(
                f"Unknown tool: {name!r}. Available: {sorted(self._specs)}"
            )
        return self._specs[name]

    def catalog(
        self,
        *,
        include_write: bool = True,
        exclude_providers: frozenset[str] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Machine-readable catalog for the reasoning loop + the UI.

        Optional prompt shaping (never affects execution allowlist):
          - include_write=False drops local-write tools (draft persistence)
            for read-only reasoning stages.
          - exclude_providers drops tools that require a live connection
            whose provider is currently disconnected (e.g. google_ads).
        ``call()`` always validates against the FULL registry — a filtered
        prompt never grants or removes capabilities.
        """
        out = []
        for s in self._specs.values():
            if not include_write and not s.read_only:
                continue
            provider = s.provider or (
                "internal" if s.category in INTERNAL_CATEGORIES else None
            )
            if (
                exclude_providers
                and s.requires_connection
                and provider in exclude_providers
            ):
                continue
            out.append(
                {
                    "name": s.name,
                    "category": s.category,
                    "description": s.description,
                    "capabilities": s.capabilities,
                    "integration_status": s.integration_status,
                    "provider": provider,
                    "requires_connection": s.requires_connection,
                    "read_only": s.read_only,
                    "write_actions": s.write_actions,
                    "writes_require_approval": s.writes_require_approval,
                }
            )
        return out

    def call(
        self, ctx: ToolContext, name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke an allowlisted tool. Returns {spec, result, latency_ms}."""
        spec = self.spec(name)  # raises for unknown tools
        fn = self._factories[name](ctx)
        t0 = time.perf_counter()
        try:
            result = fn(**params) if params else fn()
        except ToolError:
            raise
        except Exception as exc:  # tool failure isolation
            raise ToolError(f"{name} failed: {type(exc).__name__}: {exc}") from exc
        return {
            "spec": {
                "name": spec.name,
                "category": spec.category,
                "integration_status": spec.integration_status,
            },
            "result": result,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }


# Module-level singleton registry
REGISTRY = MarketingToolRegistry()


def get_registry() -> MarketingToolRegistry:
    return REGISTRY
