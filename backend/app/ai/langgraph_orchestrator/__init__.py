"""Shared LangGraph multi-agent execution architecture for RazorGrowth AI.

Provides typed workflow state, node definitions for all 14 agents, conditional
routing for fast/deep/team/growth_team modes, durable checkpointing, cancellation,
and human-approval integration.
"""
from __future__ import annotations

from backend.app.ai.langgraph_orchestrator.state import (
    GrowthWorkflowState,
)
from backend.app.ai.langgraph_orchestrator.graph import (
    build_growth_workflow_graph,
)
from backend.app.ai.langgraph_orchestrator.checkpointer import (
    DurableWorkflowCheckpointer,
)
from backend.app.ai.langgraph_orchestrator.executor import (
    LangGraphWorkflowExecutor,
)

__all__ = [
    "GrowthWorkflowState",
    "build_growth_workflow_graph",
    "DurableWorkflowCheckpointer",
    "LangGraphWorkflowExecutor",
]
