"""Research for the Product Agent — the EXISTING AgenticRAG loop, scoped.

There is no second RAG system here. This module configures
``agents.marketing_agi.rag.AgenticRAG`` — the same
retrieve → evaluate → reformulate → retrieve loop the Marketing Agent
uses — for a different agent:

  * ``type_tools`` routes retrieval to product evidence sources instead of
    marketing ones (so a product question never retrieves campaigns).
  * ``role="product"`` so the strategist prompt names the right agent.
  * ``invoke`` is the Product Agent's MCP client, so every retrieval goes
    through the shared MCP layer and its policy gates.

The allowlist (``AgenticRAG._tools``) is derived from the Product Agent's
MCP catalog, so the retrieval strategist can never name a tool outside the
agent's granted domains — customer, marketing and campaign tools are
structurally out of reach.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.app.agents.marketing_agi.limits import LoopLimits
from backend.app.agents.marketing_agi.rag import (
    AgenticRAG,
    AgenticRAGResult,
    RetrievalOutcome,
)
from backend.app.agents.product_agi import tools as agent_tools
from backend.app.agents.product_agi.state import Stage

log = logging.getLogger(__name__)

#: Retrieval routing for a PRODUCT question. Every name here is a tool the
#: Product Agent's MCP grant resolves, so the deterministic path can never
#: reach a tool outside commerce / analytics / product_intelligence.
PRODUCT_TYPE_TOOLS: dict[str, list[str]] = {
    "product": [
        "product_intelligence.get_product_opportunities",
        "commerce.get_inventory",
        "analytics.get_product_performance",
    ],
    "business": [
        "commerce.get_product_sales",
        "marketing.analytics.get_orders",
        "marketing.analytics.get_revenue",
    ],
    "inventory": [
        "product_intelligence.get_low_stock_risk",
        "commerce.get_inventory",
        "commerce.get_product_sales",
    ],
    "content": [
        "product_intelligence.get_content_gaps",
        "commerce.list_products",
    ],
    "pricing": [
        "product_intelligence.get_pricing_opportunities",
        "commerce.list_products",
    ],
    "bundle": [
        "product_intelligence.get_bundle_opportunities",
        "commerce.get_orders",
    ],
    "customer": [
        "commerce.get_orders",
        "marketing.analytics.get_customer_retention",
    ],
    "marketing": [
        "marketing.analytics.get_revenue",
        "marketing.analytics.get_campaign_history",
    ],
    "history": [
        "marketing.knowledge.recall_memory",
        "marketing.analytics.get_action_history",
    ],
    "knowledge": ["marketing.knowledge.search_knowledge_store"],
    "payments": ["marketing.analytics.get_failed_payments"],
    "unknown": [
        "product_intelligence.get_product_opportunities",
        "commerce.get_inventory",
    ],
}


class _CatalogAdapter:
    """Minimal registry shape for AgenticRAG, backed by the MCP catalog.

    ``AgenticRAG`` reads ``registry.catalog()`` for two things: the
    execution allowlist (``spec["name"]``) and, when no prompt catalog was
    supplied, the prompt. Adapting the MCP catalog here means the allowlist
    IS the agent's MCP grant — which is the point.
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def catalog(self, **_: Any) -> list[dict[str, Any]]:
        return self._entries


class ProductResearch:
    """Agentic RAG bound to one Product Agent run."""

    def __init__(
        self,
        *,
        tool_ctx: Any,
        mcp_client: Any,
        llm: Any = None,
        limits: LoopLimits | None = None,
        stage: str | Stage = Stage.research_analyze,
    ) -> None:
        entries = agent_tools.stage_catalog(mcp_client, stage)
        adapter = _CatalogAdapter(entries)
        self._rag = AgenticRAG(
            tool_ctx,
            adapter,
            llm,
            limits,
            prompt_catalog=entries,
            invoke=lambda name, params: _invoke(mcp_client, name, params),
            type_tools=PRODUCT_TYPE_TOOLS,
            role="product",
        )

    def research(self, question: str) -> AgenticRAGResult:
        return self._rag.research(question)

    @property
    def tool_names(self) -> set[str]:
        return set(self._rag._tools)  # noqa: SLF001 - allowlist introspection


def _invoke(client: Any, name: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """MCP-backed retrieval for one research round.

    Returns None when the tool has no MCP equivalent so AgenticRAG can fall
    back, and raises on a real MCP failure so the round is recorded as an
    honest gap rather than an invented result.
    """
    from backend.app.integrations.mcp import bridge as mcp_bridge

    return mcp_bridge.mcp_invoke(client, name, params)


__all__ = [
    "PRODUCT_TYPE_TOOLS",
    "AgenticRAGResult",
    "ProductResearch",
    "RetrievalOutcome",
]