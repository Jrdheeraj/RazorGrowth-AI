"""Stage → MCP discovery map for the Product Agent.

Two things live here, and both exist to keep the LLM's catalog small:

  ``STAGE_MCP_PHASE``     each agent stage names the shared MCP catalog
                          phase it may see. The MCP layer stays agent
                          agnostic (observe / research / campaign_prep /
                          execution); only the agent translates.

  ``STAGE_TOOLS``         each stage additionally names the specific tools
                          it legitimately needs. This is what stops the
                          whole granted catalog being shipped to every
                          prompt — the pre-existing prompt-bloat problem.

Discovery is a CAPABILITY GRANT, never an authorization decision:
``MCPClient.call`` still validates against the complete registry and the
policy layer still re-checks tenant, integration, approval and execution
for every single invocation.
"""
from __future__ import annotations

from typing import Iterable

from backend.app.agents.marketing_agi.limits import LoopLimits
from backend.app.agents.product_agi.state import Stage

#: This agent's loop budget. Tighter than the marketing default on purpose:
#: the Product Agent has one analysis stage, two retrieval questions and one
#: conclusion, so a larger budget only buys wasted LLM calls. The run's
#: wall-clock ceiling is what keeps the HTTP request responsive — the cycle
#: itself runs in the background.
PRODUCT_AGENT_LIMITS = LoopLimits(
    max_iterations=6,
    max_tool_calls=24,
    max_retrieval_rounds=2,
    max_llm_calls=10,
    llm_timeout_seconds=60,
    run_timeout_seconds=300,
)

#: Agent stage → shared MCP catalog phase.
STAGE_MCP_PHASE: dict[str, str] = {
    Stage.understand_catalog.value: "observe",
    Stage.analyze_performance.value: "observe",
    Stage.find_opportunities.value: "observe",
    # Research sees the observation tools too: deepening an observation is
    # exactly what a retrieval round does.
    Stage.research_analyze.value: "research",
    Stage.prepare_recommendation.value: "research",
    Stage.safety_check.value: "research",
    # Execution exposes only approval-gated external writes. The Product
    # Agent declares none, so this phase yields an empty catalog — which is
    # the honest result, not a missing feature.
    Stage.waiting_approval.value: "execution",
    Stage.execute_measure.value: "execution",
    Stage.learn.value: "research",
}

#: The tools each stage is allowed to see in its prompt catalog.
COMMERCE_CATALOG = (
    "commerce.list_products",
    "commerce.get_product",
    "commerce.get_inventory",
)
COMMERCE_DEMAND = (
    "commerce.get_product_sales",
    "commerce.get_orders",
)
COMMERCE_INVENTORY = (
    "commerce.get_low_stock_products",
)
ANALYTICS_PERFORMANCE = (
    "analytics.get_product_performance",
    "analytics.get_top_products",
    "marketing.analytics.get_orders",
)
ANALYTICS_REVENUE = (
    "marketing.analytics.get_revenue",
    "marketing.analytics.get_revenue_trend",
)
PRODUCT_INTELLIGENCE = (
    "product_intelligence.get_catalog_health",
    "product_intelligence.get_underperforming_products",
    "product_intelligence.get_low_stock_risk",
    "product_intelligence.get_content_gaps",
    "product_intelligence.get_pricing_opportunities",
    "product_intelligence.get_bundle_opportunities",
    "product_intelligence.get_product_opportunities",
)
#: Knowledge/memory evidence sources live in the analytics domain, so this
#: agent is granted them.
RESEARCH_EVIDENCE = (
    "marketing.knowledge.search_knowledge_store",
    "marketing.knowledge.recall_memory",
    "analytics.get_conversion",
)

STAGE_TOOLS: dict[str, tuple[str, ...]] = {
    Stage.understand_catalog.value: COMMERCE_CATALOG + COMMERCE_INVENTORY,
    Stage.analyze_performance.value: (
        COMMERCE_DEMAND + ANALYTICS_PERFORMANCE + ANALYTICS_REVENUE
    ),
    Stage.find_opportunities.value: PRODUCT_INTELLIGENCE,
    Stage.research_analyze.value: (
        PRODUCT_INTELLIGENCE + RESEARCH_EVIDENCE + ANALYTICS_PERFORMANCE
    ),
    Stage.prepare_recommendation.value: PRODUCT_INTELLIGENCE + ANALYTICS_PERFORMANCE,
    Stage.safety_check.value: PRODUCT_INTELLIGENCE,
    Stage.waiting_approval.value: (),
    Stage.execute_measure.value: (),
    Stage.learn.value: RESEARCH_EVIDENCE,
}

#: The complete set of tools this agent may ever name in a prompt.
ALL_AGENT_TOOLS: frozenset[str] = frozenset(
    tool for tools in STAGE_TOOLS.values() for tool in tools
)


def tools_for_stage(stage: str | Stage) -> tuple[str, ...]:
    return STAGE_TOOLS.get(Stage(stage).value, ())


def mcp_phase_for_stage(stage: str | Stage) -> str:
    return STAGE_MCP_PHASE.get(Stage(stage).value, "observe")


def grant_names(stage: str | Stage) -> list[str] | None:
    """``stage_tools`` argument for the MCP catalog. ``None`` = everything."""
    tools = tools_for_stage(stage)
    return list(tools) if tools else []


def stage_catalog(
    client: object,
    stage: str | Stage,
    *,
    include_write: bool = False,
) -> list[dict[str, object]]:
    """The Product Agent's prompt catalog for one stage.

    Always read-only: this agent declares no write tool of its own, and its
    actions go through the existing approval pipeline rather than an MCP
    write.
    """
    return client.catalog_for_agent(  # type: ignore[attr-defined]
        "product_agent",
        phase=mcp_phase_for_stage(stage),
        include_write=include_write,
        stage_tools=grant_names(stage),
    )


def iter_agent_tool_names() -> Iterable[str]:
    return sorted(ALL_AGENT_TOOLS)


__all__ = [
    "ALL_AGENT_TOOLS",
    "PRODUCT_AGENT_LIMITS",
    "STAGE_MCP_PHASE",
    "STAGE_TOOLS",
    "grant_names",
    "iter_agent_tool_names",
    "mcp_phase_for_stage",
    "stage_catalog",
    "tools_for_stage",
]