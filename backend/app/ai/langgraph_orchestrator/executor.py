"""
Execution bridge connecting GrowthAgentOrchestrator to the LangGraph architecture.

Translates orchestrator requests into LangGraph invocations and maps final graph
state back into OrchestrationSummary, preserving 100% API and test compatibility.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableConfig
from backend.app.ai.langgraph_orchestrator.checkpointer import DurableWorkflowCheckpointer
from backend.app.ai.langgraph_orchestrator.graph import build_growth_workflow_graph
from backend.app.ai.langgraph_orchestrator.state import GrowthWorkflowState
from backend.app.services.workflow_run_service import WorkflowRunService

log = logging.getLogger(__name__)


class LangGraphWorkflowExecutor:
    """Executes a growth analysis workflow using the shared LangGraph architecture."""

    def __init__(
        self,
        db: Session,
        *,
        llm: Any = None,
        embedding_provider: Any = None,
        run_service: Optional[WorkflowRunService] = None,
        checkpointer: Any = None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.embedding_provider = embedding_provider
        self.wf = run_service or WorkflowRunService(db)
        # Default to DurableWorkflowCheckpointer for safe thread-level recovery
        self.checkpointer = checkpointer or DurableWorkflowCheckpointer()
        self.graph = build_growth_workflow_graph(checkpointer=self.checkpointer)

    def execute_workflow(
        self,
        *,
        merchant_id: uuid.UUID,
        mode: str,
        orchestrator_run_id: str,
        params: Optional[dict[str, Any]] = None,
        workflow_id: uuid.UUID,
        resumed: bool = False,
        generation: int = 1,
    ) -> dict[str, Any]:
        """Run the LangGraph workflow and return the terminal state dictionary."""
        params = params or {}
        objective = str(params.get("objective") or "Improve overall growth")
        window_days = int(params.get("window_days", 30))

        initial_state: GrowthWorkflowState = {
            "merchant_id": str(merchant_id),
            "run_id": orchestrator_run_id,
            "workflow_id": str(workflow_id),
            "mode": mode,
            "objective": objective,
            "window_days": window_days,
            "params": params,
            "generation": generation,
            "current_step_index": 0,
            "selected_specialists": [],
            "agents_run": [],
            "resumed_steps": [],
            "needs_reconciliation": [],
            "opportunities": [],
            "ranked_opportunities": [],
            "findings": [],
            "actions_proposed": [],
            "tool_records": [],
            "shared_memory": {},
            "errors": [],
            "status": "running",
            "cancelled": False,
            "cancelled_at_step": None,
            "totals": {},
            "debate_id": None,
            "action_plan": None,
            "terminal_outcome": {},
        }

        config: RunnableConfig = {
            "configurable": {
                "db": self.db,
                "llm": self.llm,
                "embedding_provider": self.embedding_provider,
                "wf": self.wf,
                "thread_id": orchestrator_run_id,
            }
        }

        try:
            final_state = self.graph.invoke(initial_state, config=config)
            return final_state
        except Exception as exc:
            log.exception("LangGraph workflow execution crashed for %s: %s", orchestrator_run_id, exc)
            return {
                "merchant_id": str(merchant_id),
                "run_id": orchestrator_run_id,
                "workflow_id": str(workflow_id),
                "mode": mode,
                "status": "failed",
                "errors": [str(exc)],
                "agents_run": [],
                "totals": {},
                "ranked_opportunities": [],
            }
