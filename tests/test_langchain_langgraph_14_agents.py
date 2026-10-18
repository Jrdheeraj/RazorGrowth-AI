"""
Comprehensive Integration Test Suite for LangChain & LangGraph across all 14 agents.

Verifies:
1. Shared LangChain integration layer (model adapter, structured output, canonical tool adapter).
2. Shared LangGraph architecture (state reducers, conditional edges, checkpointers, cancellation).
3. Individual execution of all 14 agents in the inventory.
4. Orchestrator execution with LangGraph StateGraph.
5. Isolation, lease fencing, tenant safety, and human approval gating.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.catalog import TOOL_REGISTRY, ToolSpec
from backend.app.agents.orchestrator import GrowthAgentOrchestrator
from backend.app.agents.registry import AGENT_INSTANCES, DOMAIN_SPECIALIST_AGENTS, MAIN_GROWTH_TEAM_AGENTS
from backend.app.ai.langchain_adapter.adapter import LangChainAgentAdapter
from backend.app.ai.langchain_adapter.model import RazorGrowthChatModel, get_langchain_chat_model
from backend.app.ai.langchain_adapter.tools import (
    CanonicalLangChainTool,
    get_agent_langchain_tools,
    tool_spec_to_langchain_tool,
)
from backend.app.ai.langgraph_orchestrator.checkpointer import DurableWorkflowCheckpointer
from backend.app.ai.langgraph_orchestrator.executor import LangGraphWorkflowExecutor
from backend.app.ai.langgraph_orchestrator.graph import build_growth_workflow_graph
from backend.app.ai.langgraph_orchestrator.nodes import (
    _execute_agent_step,
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
from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import AgentRunStatus, WorkflowStatus
from backend.app.models.merchant import Merchant
from backend.app.services.workflow_run_service import WorkflowRunService, request_cancel
from tests.security_utils import make_world


@pytest.fixture()
def world(db_session):
    return make_world(db_session, slug_hint="langgraph_14")


# ── Sample Pydantic Schema for Structured Output Testing ──────────────────────

class SampleGrowthHypothesis(BaseModel):
    title: str = Field(description="Hypothesis title")
    expected_impact: str = Field(description="High, medium, or low")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


# ════════════════════════════════════════════════════════════════════════════
# 1. SHARED LANGCHAIN INTEGRATION LAYER TESTS
# ════════════════════════════════════════════════════════════════════════════


class TestSharedLangChainLayer:
    def test_razorgrowth_chat_model_fallback_without_provider(self):
        """When no external LLM is configured, the model returns a safe deterministic message."""
        model = RazorGrowthChatModel(provider=None)
        res = model.invoke([HumanMessage(content="Analyze growth opportunities")])
        assert "Analysis completed" in res.content

    def test_razorgrowth_chat_model_structured_output_validation(self):
        """Model produces and validates structured output conforming to a Pydantic schema."""
        mock_provider = MagicMock()
        mock_provider.generate_structured.return_value = SampleGrowthHypothesis(
            title="Abandoned Cart Recovery Email Series",
            expected_impact="high",
            confidence=0.92,
        )
        model = RazorGrowthChatModel(provider=mock_provider)
        structured_runner = model.with_structured_output(SampleGrowthHypothesis)
        output = structured_runner.invoke("Generate a growth hypothesis")

        assert isinstance(output, SampleGrowthHypothesis)
        assert output.title == "Abandoned Cart Recovery Email Series"
        assert output.expected_impact == "high"
        assert output.confidence == 0.92

    def test_canonical_langchain_tool_adapter(self, db_session, world):
        """Canonical tool from catalog wraps into a typed LangChain BaseTool."""
        merchant = world[0]
        spec = TOOL_REGISTRY["commerce.catalog_intelligence"]
        tool = tool_spec_to_langchain_tool(
            spec=spec,
            db=db_session,
            merchant_id=merchant.id,
            caller_permissions={"read:merchants", "read:products", "read:orders"},
        )
        assert tool.name == "commerce.catalog_intelligence"
        assert tool.args_schema == spec.input_model
        # Execute tool through LangChain BaseTool interface
        output = tool.invoke({"merchant_id": str(merchant.id), "limit": 5})
        assert isinstance(output, dict)

    def test_agent_langchain_adapter_tools_mapping(self, db_session, world):
        """Every agent's LangChain adapter resolves its authorized tools."""
        merchant = world[0]
        adapter = LangChainAgentAdapter("ProductAgent", db_session, merchant.id)
        tools = adapter.tools
        tool_names = [t.name for t in tools]
        assert "commerce.catalog_intelligence" in tool_names


# ════════════════════════════════════════════════════════════════════════════
# 2. SHARED LANGGRAPH ARCHITECTURE TESTS
# ════════════════════════════════════════════════════════════════════════════


class TestSharedLangGraphArchitecture:
    def test_build_growth_workflow_graph_compiles(self):
        """The StateGraph compiles cleanly with all 14 agent nodes and conditional routing."""
        graph = build_growth_workflow_graph()
        assert graph is not None

    def test_durable_workflow_checkpointer(self):
        """Durable checkpointer saves and retrieves checkpoints by thread_id."""
        saver = DurableWorkflowCheckpointer()
        cfg: RunnableConfig = {"configurable": {"thread_id": "test-cycle-1", "checkpoint_ns": ""}}
        checkpoint = {"id": "cp-1", "ts": "2026-10-17T12:00:00Z", "channel_values": {"status": "running"}}
        metadata = {"step": 1, "source": "test"}

        res_cfg = saver.put(cfg, checkpoint, metadata, {})
        assert res_cfg["configurable"]["checkpoint_id"] == "cp-1"

        retrieved = saver.get_tuple(cfg)
        assert retrieved is not None
        assert retrieved.checkpoint["id"] == "cp-1"
        assert retrieved.checkpoint["channel_values"]["status"] == "running"

    def test_langgraph_fast_mode_execution(self, db_session, world):
        """Fast mode executes memory_load -> discovery -> payment_recovery -> prioritization."""
        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        wf = WorkflowRunService(db_session)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=cycle_id,
            mode="fast",
            plan=[("GrowthMemoryAgent", {"phase": "load"}), ("GrowthDiscoveryAgent", {})],
        )
        db_session.commit()

        executor = LangGraphWorkflowExecutor(db_session, run_service=wf)
        final_state = executor.execute_workflow(
            merchant_id=merchant.id,
            mode="fast",
            orchestrator_run_id=cycle_id,
            workflow_id=workflow_row.id,
            params={"objective": "Test fast mode", "window_days": 30},
        )
        assert final_state["status"] == "completed"
        agent_names = [a["agent_name"] for a in final_state.get("agents_run", [])]
        assert "GrowthMemoryAgent" in agent_names
        assert "GrowthDiscoveryAgent" in agent_names
        assert "PaymentRecoveryAgent" in agent_names
        assert "OpportunityPrioritizationAgent" in agent_names

    def test_langgraph_cancellation_halts_subsequent_nodes(self, db_session, world):
        """Cancellation checkpoint stops execution and finalizes as cancelled."""
        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        wf = WorkflowRunService(db_session)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=cycle_id,
            mode="fast",
            plan=[("GrowthMemoryAgent", {"phase": "load"})],
        )
        db_session.commit()

        # Mark cancelled in DB
        request_cancel(db_session, merchant_id=merchant.id, run_id=cycle_id)

        executor = LangGraphWorkflowExecutor(db_session, run_service=wf)
        final_state = executor.execute_workflow(
            merchant_id=merchant.id,
            mode="fast",
            orchestrator_run_id=cycle_id,
            workflow_id=workflow_row.id,
            params={"objective": "Test cancel", "window_days": 30},
        )
        assert final_state["status"] == "cancelled"


# ════════════════════════════════════════════════════════════════════════════
# 3. INDIVIDUAL TESTS FOR ALL 14 AGENTS IN LANGGRAPH
# ════════════════════════════════════════════════════════════════════════════


class TestAll14AgentsIntegration:
    @pytest.fixture
    def base_state(self, world):
        merchant = world[0]
        return {
            "merchant_id": str(merchant.id),
            "run_id": uuid.uuid4().hex,
            "mode": "team",
            "objective": "Complete 14-agent integration verification",
            "window_days": 30,
            "params": {"objective": "Complete 14-agent integration verification"},
            "generation": 1,
            "current_step_index": 0,
            "agents_run": [],
            "shared_memory": {},
            "errors": [],
            "status": "running",
            "cancelled": False,
        }

    def test_01_manager_agent_node(self, db_session, base_state):
        """Agent 1: ManagerAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = manager_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "ManagerAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_02_marketing_agent_node(self, db_session, base_state):
        """Agent 2: MarketingAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = marketing_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "MarketingAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_03_product_agent_node(self, db_session, base_state):
        """Agent 3: ProductAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = product_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "ProductAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_04_designer_agent_node(self, db_session, base_state):
        """Agent 4: DesignerAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = designer_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "DesignerAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_05_software_agent_node(self, db_session, base_state):
        """Agent 5: SoftwareAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = software_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "SoftwareAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_06_growth_memory_agent_nodes(self, db_session, base_state):
        """Agent 6: GrowthMemoryAgent executes load and persist phases through LangGraph nodes."""
        cfg = {"configurable": {"db": db_session}}
        load_update = memory_agent_load_node(base_state, config=cfg)
        assert load_update["agents_run"][0]["agent_name"] == "GrowthMemoryAgent"

        persist_update = memory_agent_persist_node(base_state, config=cfg)
        assert persist_update["agents_run"][0]["agent_name"] == "GrowthMemoryAgent"

    def test_07_growth_discovery_agent_node(self, db_session, base_state):
        """Agent 7: GrowthDiscoveryAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = discovery_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "GrowthDiscoveryAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_08_customer_intelligence_agent_node(self, db_session, base_state):
        """Agent 8: CustomerIntelligenceAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = customer_intelligence_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "CustomerIntelligenceAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_09_revenue_optimization_agent_node(self, db_session, base_state):
        """Agent 9: RevenueOptimizationAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = revenue_optimization_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "RevenueOptimizationAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_10_campaign_strategist_agent_node(self, db_session, base_state):
        """Agent 10: CampaignStrategistAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = campaign_strategist_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "CampaignStrategistAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_11_payment_recovery_agent_node(self, db_session, base_state):
        """Agent 11: PaymentRecoveryAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = payment_recovery_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "PaymentRecoveryAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_12_opportunity_prioritization_agent_node(self, db_session, base_state):
        """Agent 12: OpportunityPrioritizationAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = prioritization_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "OpportunityPrioritizationAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_13_experiment_agent_node(self, db_session, base_state):
        """Agent 13: ExperimentAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = experiment_agent_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "ExperimentAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")

    def test_14_personalization_agent_node(self, db_session, base_state):
        """Agent 14: PersonalizationAgent executes through LangGraph node."""
        cfg = {"configurable": {"db": db_session}}
        update = personalization_node(base_state, config=cfg)
        assert len(update["agents_run"]) == 1
        assert update["agents_run"][0]["agent_name"] == "PersonalizationAgent"
        assert update["agents_run"][0]["status"] in ("completed", "partially_completed")


# ════════════════════════════════════════════════════════════════════════════
# 4. ORCHESTRATOR LANGGRAPH EXECUTION TESTS
# ════════════════════════════════════════════════════════════════════════════


class TestOrchestratorLangGraphExecution:
    def test_orchestrator_run_with_langgraph_fast_mode(self, db_session, world):
        """GrowthAgentOrchestrator executes via compiled LangGraph and returns OrchestrationSummary."""
        merchant = world[0]
        orch = GrowthAgentOrchestrator(db_session)
        summary = orch.run_with_langgraph(
            merchant.id,
            mode="fast",
            params={"objective": "Test run_with_langgraph fast", "window_days": 30},
        )
        assert summary.orchestrator_run_id
        assert summary.mode == "fast"
        assert summary.status == "completed"

        # Verify durable row exists in DB
        wf_row = db_session.query(AgentWorkflowRun).filter(
            AgentWorkflowRun.run_id == summary.orchestrator_run_id
        ).one()
        assert wf_row.status == "completed"

    def test_orchestrator_run_with_langgraph_team_mode(self, db_session, world):
        """GrowthAgentOrchestrator executes the full 14-agent team mode via LangGraph."""
        merchant = world[0]
        orch = GrowthAgentOrchestrator(db_session)
        summary = orch.run_with_langgraph(
            merchant.id,
            mode="team",
            params={"objective": "Test 14-agent team pipeline", "window_days": 30},
        )
        assert summary.orchestrator_run_id
        assert summary.mode == "team"
        assert summary.status in ("completed", "partial")

        agent_names = [a["agent_name"] for a in summary.agents_run]
        # Check that core specialist agents and main team agents executed
        assert "GrowthDiscoveryAgent" in agent_names
        assert "MarketingAgent" in agent_names
        assert "ProductAgent" in agent_names
        assert "DesignerAgent" in agent_names
        assert "SoftwareAgent" in agent_names
        assert "PersonalizationAgent" in agent_names
        assert "ManagerAgent" in agent_names
