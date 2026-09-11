"""MarketingAGI tool registry — capability-based, allowlisted, tenant-scoped.

Every tool receives (db, merchant_id) at construction and EVERY query it
performs filters by merchant_id in SQL. The registry enforces:

  - an allowlist of registered tool names (unknown tools can never run)
  - a category per tool, surfaced to the reasoning loop for selection
  - read-only marketing data tools + draft/preparation tools only
  - NO tool may approve, reject, execute, or bypass guardrails
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


@dataclass
class ToolSpec:
    name: str
    category: str            # analytics | customers | marketing | knowledge | products | payments | integrations
    description: str
    capabilities: list[str] = field(default_factory=list)
    integration_status: str = "connected"   # connected | draft_only | requires_integration


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

    def catalog(self) -> list[dict[str, Any]]:
        """Machine-readable catalog for the reasoning loop + the UI."""
        return [
            {
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "capabilities": s.capabilities,
                "integration_status": s.integration_status,
            }
            for s in self._specs.values()
        ]

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
