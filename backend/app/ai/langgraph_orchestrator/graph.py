"""
LangGraph Multi-Agent Growth Graph Builder.

Constructs the executable StateGraph wiring all 14 agents into conditional
execution flows according to the requested mode (fast, deep, team, growth_team).
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.app.ai.langgraph_orchestrator.nodes import (
    campaign_strategist_node,
    customer_intelligence_node,
    designer_agent_node,
    discovery_agent_node,
    experiment_agent_node,
    finalize_workflow_node,
    load_context_node,
    manager_agent_node,
    marketing_agent_node,
    memory_agent_load_node,
    memory_agent_persist_node,
    payment_recovery_node,
    personalization_node,
    prioritization_node,
    product_agent_node,
    revenue_optimization_node,
    software_agent_node,
    validate_request_node,
)
from backend.app.ai.langgraph_orchestrator.state import GrowthWorkflowState

log = logging.getLogger(__name__)


def _route_by_mode(state: GrowthWorkflowState) -> str:
    """Route initial graph dispatch to the first specialized node according to mode."""
    if state.get("cancelled", False):
        return "finalize_workflow"

    mode = state.get("mode", "deep")
    if mode == "fast":
        return "fast_memory_load"
    elif mode == "team":
        return "team_memory_load"
    elif mode == "growth_team":
        return "growth_team_memory_load"
    return "deep_memory_load"


def _check_cancellation(state: GrowthWorkflowState, next_node: str) -> str:
    """Check if cancellation was requested; if so, jump directly to finalization."""
    if state.get("cancelled", False):
        return "finalize_workflow"
    return next_node


def build_growth_workflow_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Construct and compile the authoritative LangGraph StateGraph across all 14 agents."""
    builder = StateGraph(GrowthWorkflowState)

    # 1. Pipeline foundation nodes
    builder.add_node("validate_request", validate_request_node)
    builder.add_node("load_context", load_context_node)
    builder.add_node("finalize_workflow", finalize_workflow_node)

    # 2. Mode: FAST nodes
    builder.add_node("fast_memory_load", memory_agent_load_node)
    builder.add_node("fast_discovery", discovery_agent_node)
    builder.add_node("fast_payment_recovery", payment_recovery_node)
    builder.add_node("fast_prioritization", prioritization_node)

    # 3. Mode: DEEP nodes
    builder.add_node("deep_memory_load", memory_agent_load_node)
    builder.add_node("deep_discovery", discovery_agent_node)
    builder.add_node("deep_customer_intel", customer_intelligence_node)
    builder.add_node("deep_payment_recovery", payment_recovery_node)
    builder.add_node("deep_campaign_strategist", campaign_strategist_node)
    builder.add_node("deep_revenue_opt", revenue_optimization_node)
    builder.add_node("deep_experiment", experiment_agent_node)
    builder.add_node("deep_prioritization", prioritization_node)
    builder.add_node("deep_memory_persist", memory_agent_persist_node)

    # 4. Mode: TEAM (AI Team Workspace 14-Agent Coordinated Pipeline) nodes
    builder.add_node("team_memory_load", memory_agent_load_node)
    builder.add_node("team_discovery", discovery_agent_node)
    builder.add_node("team_customer_intel", customer_intelligence_node)
    builder.add_node("team_revenue_opt", revenue_optimization_node)
    builder.add_node("team_payment_recovery", payment_recovery_node)
    builder.add_node("team_marketing", marketing_agent_node)
    builder.add_node("team_product", product_agent_node)
    builder.add_node("team_campaign_strategist", campaign_strategist_node)
    builder.add_node("team_designer", designer_agent_node)
    builder.add_node("team_experiment", experiment_agent_node)
    builder.add_node("team_prioritization", prioritization_node)
    builder.add_node("team_software", software_agent_node)
    builder.add_node("team_personalization", personalization_node)
    builder.add_node("team_manager", manager_agent_node)
    builder.add_node("team_memory_persist", memory_agent_persist_node)

    # 5. Mode: GROWTH_TEAM (4-Round Multi-Agent Collaboration) nodes
    builder.add_node("growth_team_memory_load", memory_agent_load_node)
    builder.add_node("growth_team_manager_plan", manager_agent_node)
    builder.add_node("growth_team_marketing", marketing_agent_node)
    builder.add_node("growth_team_product", product_agent_node)
    builder.add_node("growth_team_designer", designer_agent_node)
    builder.add_node("growth_team_software", software_agent_node)
    builder.add_node("growth_team_prioritization", prioritization_node)
    builder.add_node("growth_team_manager_synth", manager_agent_node)
    builder.add_node("growth_team_memory_persist", memory_agent_persist_node)

    # ── EDGES ──────────────────────────────────────────────────────────

    # Flow initialization
    builder.add_edge(START, "validate_request")
    builder.add_edge("validate_request", "load_context")

    # Dynamic routing to mode entry point
    builder.add_conditional_edges(
        "load_context",
        _route_by_mode,
        {
            "fast_memory_load": "fast_memory_load",
            "deep_memory_load": "deep_memory_load",
            "team_memory_load": "team_memory_load",
            "growth_team_memory_load": "growth_team_memory_load",
            "finalize_workflow": "finalize_workflow",
        },
    )

    # Fast Mode Chain
    builder.add_edge("fast_memory_load", "fast_discovery")
    builder.add_edge("fast_discovery", "fast_payment_recovery")
    builder.add_edge("fast_payment_recovery", "fast_prioritization")
    builder.add_edge("fast_prioritization", "finalize_workflow")

    # Deep Mode Chain
    builder.add_edge("deep_memory_load", "deep_discovery")
    builder.add_edge("deep_discovery", "deep_customer_intel")
    builder.add_edge("deep_customer_intel", "deep_payment_recovery")
    builder.add_edge("deep_payment_recovery", "deep_campaign_strategist")
    builder.add_edge("deep_campaign_strategist", "deep_revenue_opt")
    builder.add_edge("deep_revenue_opt", "deep_experiment")
    builder.add_edge("deep_experiment", "deep_prioritization")
    builder.add_edge("deep_prioritization", "deep_memory_persist")
    builder.add_edge("deep_memory_persist", "finalize_workflow")

    # Team Mode Chain (14 Agents)
    builder.add_edge("team_memory_load", "team_discovery")
    builder.add_edge("team_discovery", "team_customer_intel")
    builder.add_edge("team_customer_intel", "team_revenue_opt")
    builder.add_edge("team_revenue_opt", "team_payment_recovery")
    builder.add_edge("team_payment_recovery", "team_marketing")
    builder.add_edge("team_marketing", "team_product")
    builder.add_edge("team_product", "team_campaign_strategist")
    builder.add_edge("team_campaign_strategist", "team_designer")
    builder.add_edge("team_designer", "team_experiment")
    builder.add_edge("team_experiment", "team_prioritization")
    builder.add_edge("team_prioritization", "team_software")
    builder.add_edge("team_software", "team_personalization")
    builder.add_edge("team_personalization", "team_manager")
    builder.add_edge("team_manager", "team_memory_persist")
    builder.add_edge("team_memory_persist", "finalize_workflow")

    # Growth Team Mode Chain
    builder.add_edge("growth_team_memory_load", "growth_team_manager_plan")
    builder.add_edge("growth_team_manager_plan", "growth_team_marketing")
    builder.add_edge("growth_team_marketing", "growth_team_product")
    builder.add_edge("growth_team_product", "growth_team_designer")
    builder.add_edge("growth_team_designer", "growth_team_software")
    builder.add_edge("growth_team_software", "growth_team_prioritization")
    builder.add_edge("growth_team_prioritization", "growth_team_manager_synth")
    builder.add_edge("growth_team_manager_synth", "growth_team_memory_persist")
    builder.add_edge("growth_team_memory_persist", "finalize_workflow")

    # Terminal edge
    builder.add_edge("finalize_workflow", END)

    return builder.compile(checkpointer=checkpointer)
