"""
Execution nodes for all 14 agents in the shared LangGraph architecture.

Every agent is represented by an explicit node or subgraph, maintaining:
- Isolated savepoints so one broken agent cannot corrupt other agents
- Structured AgentRun audit rows committed per step
- Canonical tool catalog dispatch and permission validation
- Cooperative cancellation checks before each agent runs
- Bounded execution and error handling
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableConfig

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.catalog import TOOL_REGISTRY, invoke
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.ai.langchain_adapter.adapter import LangChainAgentAdapter
from backend.app.ai.langgraph_orchestrator.state import GrowthWorkflowState
from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import AgentRunStatus, WorkflowStatus
from backend.app.services.workflow_run_service import (
    ReuseVerdict,
    is_cancel_requested,
    step_key as step_key_for,
)

log = logging.getLogger(__name__)


def _get_execution_context(config: Optional[RunnableConfig]) -> tuple[Optional[Session], Any, Any, Any]:
    """Extract runtime dependencies from LangGraph RunnableConfig."""
    if config is None:
        return None, None, None, None
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    llm = configurable.get("llm")
    embedding_provider = configurable.get("embedding_provider")
    wf = configurable.get("wf")
    return db, llm, embedding_provider, wf


def _execute_agent_step(
    agent_name: str,
    state: GrowthWorkflowState,
    config: Optional[RunnableConfig],
    *,
    phase: Optional[str] = None,
    custom_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Generic, resilient step executor for any of the 14 agents."""
    from backend.app.services.agent_run_service import AgentRunService
    from backend.app.services.workflow_run_service import current_workflow

    db, llm, embedding_provider, wf = _get_execution_context(config)
    merchant_id_str = state.get("merchant_id", "")
    merchant_id = uuid.UUID(merchant_id_str) if merchant_id_str else uuid.uuid4()
    run_id = state.get("run_id", uuid.uuid4().hex)
    mode = state.get("mode", "deep")
    workflow_id_str = state.get("workflow_id")
    workflow_id = uuid.UUID(workflow_id_str) if workflow_id_str else None
    generation = state.get("generation", 1)
    step_idx = state.get("current_step_index", 0)

    # 1. Cooperative cancellation check
    if state.get("cancelled", False) or (db and workflow_id and is_cancel_requested(db, workflow_id)):
        log.info("Cancellation detected before executing %s in cycle %s", agent_name, run_id)
        return {
            "cancelled": True,
            "status": "cancelled",
            "errors": [f"{agent_name} cancelled before execution"],
        }

    agent = AGENT_INSTANCES.get(agent_name)
    if agent is None:
        log.error("Agent %s not found in registry", agent_name)
        return {"errors": [f"Unknown agent: {agent_name}"]}

    step_key_val = step_key_for(mode, step_idx, agent_name, phase)

    # 2. Check for reusable step on resume
    if db and workflow_id and wf:
        attempts = wf.attempt_rows(workflow_id)
        if step_key_val in attempts:
            prior = attempts[step_key_val]
            decision = wf.decide(step_row=prior, merchant_id=merchant_id)
            if decision.verdict is ReuseVerdict.REUSE:
                log.info("Reusing step %s for %s (already completed)", step_key_val, agent_name)
                prior_output = dict(prior.output_summary or {})
                reused_item = {
                    "agent_name": agent_name,
                    "step_key": step_key_val,
                    "status": getattr(prior.status, "value", str(prior.status)),
                    "opportunities_created": prior.opportunities_created or 0,
                    "actions_proposed": prior.actions_proposed or 0,
                    "tools_used": prior.tools_used or [],
                    "errors": prior.errors or [],
                    "reused": True,
                }
                updates: dict[str, Any] = {
                    "current_step_index": step_idx + 1,
                    "agents_run": [reused_item],
                    "resumed_steps": [
                        {
                            "step_index": step_idx,
                            "step_key": step_key_val,
                            "agent": agent_name,
                            "phase": phase,
                        }
                    ],
                }
                # Replay the persisted result into the cross-agent scratchpad,
                # using the SAME mapping as the live/legacy path. Without this a
                # resumed cycle silently loses the completed agent's findings
                # for every downstream agent.
                from backend.app.agents.orchestrator import _publish_findings

                shared_updates: dict[str, Any] = {}
                _publish_findings(agent_name, prior_output, shared_updates)
                if shared_updates:
                    updates["shared_memory"] = shared_updates
                # The Manager's persisted output owns the cycle-level results.
                # Only published when the step actually recorded them, so a
                # Manager step that produced neither cannot fabricate them.
                if agent_name == "ManagerAgent":
                    if prior_output.get("debate_id"):
                        updates["debate_id"] = str(prior_output["debate_id"])
                    if "action_plan" in prior_output:
                        updates["action_plan"] = prior_output["action_plan"]
                return updates

    # Prepare step parameters
    step_params = dict(state.get("params") or {})
    if custom_params:
        step_params.update(custom_params)
    if phase:
        step_params["phase"] = phase
    step_params["orchestrator_run_id"] = run_id
    if workflow_id:
        step_params["workflow_run_id"] = str(workflow_id)

    # Prepare context and shared state
    shared_ctx = dict(state.get("shared_memory") or {})
    if "rag_context" in shared_ctx:
        step_params["_rag_context"] = shared_ctx["rag_context"]

    # Growth team debate coordination
    if mode == "growth_team":
        if "manager_debate_id" in shared_ctx:
            step_params["debate_id"] = shared_ctx["manager_debate_id"]
        if agent_name in {"MarketingAgent", "ProductAgent", "DesignerAgent", "SoftwareAgent"}:
            if "manager_delegations" in shared_ctx:
                for delegation in shared_ctx["manager_delegations"]:
                    assigned = delegation.get("assigned_to", "").lower()
                    if assigned == agent_name.lower().replace("agent", ""):
                        step_params["task_id"] = delegation.get("task_id")
                        break

    ctx = AgentContext(
        db=db,
        merchant_id=merchant_id,
        mode=mode,
        params=step_params,
        llm=llm,
        embedding_provider=embedding_provider,
        shared=shared_ctx,
    )

    # Initialize LangChain adapter
    langchain_adapter = LangChainAgentAdapter(
        agent_name=agent_name,
        db=db,
        merchant_id=merchant_id,
        llm=llm,
    )
    ctx.shared["langchain_adapter"] = langchain_adapter

    # 3. Heartbeat & audit row setup via AgentRunService
    run_row: Optional[AgentRun] = None
    if db and workflow_id and wf:
        try:
            wf_row = db.get(AgentWorkflowRun, workflow_id)
            if wf_row:
                wf.heartbeat(wf_row, expected_generation=generation)
                db.commit()

            run_service = AgentRunService(db)
            attempt_num = wf.next_attempt(workflow_id, step_key_val)
            run_row = run_service.start_run(
                merchant_id=merchant_id,
                agent_name=agent_name,
                orchestrator_run_id=run_id,
                mode=mode,
                input_summary={"params": step_params},
                workflow_id=workflow_id,
                step_key=step_key_val,
                step_index=step_idx,
                attempt=attempt_num,
            )
            run_service.commit_start()
        except Exception as e:
            log.warning("Could not persist initial AgentRun row for %s: %s", agent_name, e)
            try:
                db.rollback()
            except Exception:
                pass

    # 4. Execution under isolated savepoint and scoped workflow idempotency
    result = AgentResult(agent_name=agent_name)
    savepoint = None
    if db:
        try:
            savepoint = db.begin_nested()
        except Exception:
            pass

    try:
        with current_workflow(workflow_id):
            result = agent.execute(ctx)
        if savepoint:
            if result.ok:
                savepoint.commit()
            else:
                savepoint.rollback()
        if db:
            db.commit()
    except Exception as exc:
        log.exception("Agent %s failed during LangGraph execution: %s", agent_name, exc)
        if savepoint:
            try:
                savepoint.rollback()
            except Exception:
                pass
        result = AgentResult(agent_name=agent_name, status="failed")
        result.errors.append(str(exc))

    # 5. Finalize AgentRun audit row via AgentRunService
    if db and run_row is not None:
        try:
            run_service = AgentRunService(db)
            run_service.complete_run(run_row, result)
            db.commit()
        except Exception as e:
            log.warning("Could not finalize AgentRun audit row for %s: %s", agent_name, e)
            try:
                db.rollback()
            except Exception:
                pass

    # 6. Extract state updates
    state_updates: dict[str, Any] = {
        "current_step_index": step_idx + 1,
        "agents_run": [
            {
                "agent_name": agent_name,
                "step_key": step_key_val,
                "status": result.status,
                "opportunities_created": result.opportunities_created,
                "actions_proposed": result.actions_proposed,
                "tools_used": result.tools_used,
                "errors": result.errors,
            }
        ],
        "shared_memory": ctx.shared,
    }

    if result.errors:
        state_updates["errors"] = result.errors

    if "opportunities" in result.output and isinstance(result.output["opportunities"], list):
        state_updates["opportunities"] = result.output["opportunities"]

    if "proposed_actions" in result.output and isinstance(result.output["proposed_actions"], list):
        state_updates["actions_proposed"] = result.output["proposed_actions"]

    if "findings" in result.output and isinstance(result.output["findings"], list):
        state_updates["findings"] = result.output["findings"]

    if "ranked" in result.output and isinstance(result.output["ranked"], list):
        state_updates["ranked_opportunities"] = result.output["ranked"]
    elif "ranked_opportunities" in ctx.shared and isinstance(ctx.shared["ranked_opportunities"], list):
        state_updates["ranked_opportunities"] = ctx.shared["ranked_opportunities"]

    # Cycle-level outputs produced by the Manager. `debate_id` only exists when
    # a real AgentDebate row was created or retrieved, and `action_plan` only
    # when the Manager actually coordinated one. Absent output leaves the state
    # fields unset rather than inventing a value.
    if agent_name == "ManagerAgent" and isinstance(result.output, dict):
        if result.output.get("debate_id"):
            state_updates["debate_id"] = str(result.output["debate_id"])
        if "action_plan" in result.output:
            state_updates["action_plan"] = result.output["action_plan"]

    return state_updates


# ════════════════════════════════════════════════════════════════════════════
# 14 INDIVIDUAL AGENT NODES
# ════════════════════════════════════════════════════════════════════════════


def manager_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """1. ManagerAgent: Growth objective coordination and specialist delegation."""
    phase = "coordinate" if state.get("mode") == "team" else "delegate"
    return _execute_agent_step("ManagerAgent", state, config, phase=phase)


def marketing_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """2. MarketingAgent: Audience segmentation, retention, and campaign strategy."""
    phase = "work" if state.get("mode") == "team" else "investigate"
    return _execute_agent_step("MarketingAgent", state, config, phase=phase)


def product_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """3. ProductAgent: Catalog intelligence, upsell/cross-sell, and affinity analysis."""
    phase = "work" if state.get("mode") == "team" else "investigate"
    return _execute_agent_step("ProductAgent", state, config, phase=phase)


def designer_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """4. DesignerAgent: Creative brief generation, concepts, and messaging variants."""
    phase = "work" if state.get("mode") == "team" else "investigate"
    return _execute_agent_step("DesignerAgent", state, config, phase=phase)


def software_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """5. SoftwareAgent: Technical feasibility, integration specs, and dependency mapping."""
    phase = "work" if state.get("mode") == "team" else "investigate"
    return _execute_agent_step("SoftwareAgent", state, config, phase=phase)


def memory_agent_load_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """6a. GrowthMemoryAgent (load phase): Retrieve historical learnings and context."""
    return _execute_agent_step("GrowthMemoryAgent", state, config, phase="load")


def memory_agent_persist_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """6b. GrowthMemoryAgent (persist phase): Safely commit approved learnings to memory."""
    return _execute_agent_step("GrowthMemoryAgent", state, config, phase="persist")


def discovery_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """7. GrowthDiscoveryAgent: Growth radar signals and leakage detection."""
    return _execute_agent_step("GrowthDiscoveryAgent", state, config)


def customer_intelligence_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """8. CustomerIntelligenceAgent: RFM segmentation, LTV, and churn prediction."""
    return _execute_agent_step("CustomerIntelligenceAgent", state, config)


def revenue_optimization_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """9. RevenueOptimizationAgent: Pricing elasticity, margin, and bundle analysis."""
    return _execute_agent_step("RevenueOptimizationAgent", state, config)


def campaign_strategist_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """10. CampaignStrategistAgent: Multi-channel targeting and campaign proposals."""
    return _execute_agent_step("CampaignStrategistAgent", state, config)


def payment_recovery_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """11. PaymentRecoveryAgent: Failed transaction analysis and recovery recommendations."""
    return _execute_agent_step("PaymentRecoveryAgent", state, config)


def prioritization_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """12. OpportunityPrioritizationAgent: ICE scoring, effort estimation, and ranking."""
    return _execute_agent_step("OpportunityPrioritizationAgent", state, config)


def experiment_agent_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """13. ExperimentAgent: Growth experiment design, variants, and metrics."""
    return _execute_agent_step("ExperimentAgent", state, config)


def personalization_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """14. PersonalizationAgent: Per-customer next-best-action decisioning."""
    return _execute_agent_step("PersonalizationAgent", state, config)


# ════════════════════════════════════════════════════════════════════════════
# PIPELINE COORDINATION NODES
# ════════════════════════════════════════════════════════════════════════════


def validate_request_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Validate merchant tenancy and lease ownership before graph execution."""
    db, _, _, wf = _get_execution_context(config)
    merchant_id_str = state.get("merchant_id", "")
    workflow_id_str = state.get("workflow_id")
    run_id = state.get("run_id", "")

    if not merchant_id_str:
        return {"status": "failed", "errors": ["Missing required merchant_id"]}

    # Ensure initial status is running
    return {
        "status": "running",
        "current_step_index": 0,
        "cancelled": False,
    }


def load_context_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Load RAG context and merchant signals into shared memory."""
    db, _, _, _ = _get_execution_context(config)
    merchant_id_str = state.get("merchant_id", "")
    if not db or not merchant_id_str:
        return {}

    try:
        from backend.app.services.rag_context import RAGContextService
        merchant_id = uuid.UUID(merchant_id_str)
        objective = state.get("objective") or "growth opportunity analysis"
        window_days = state.get("window_days", 30)
        rag_data = RAGContextService(db).build(merchant_id, objective, window_days=window_days)
        db.commit()
        return {"shared_memory": {"rag_context": rag_data}}
    except Exception as exc:
        log.warning("Could not initialize RAG context in load_context_node: %s", exc)
        return {}


def finalize_workflow_node(state: GrowthWorkflowState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Persist final terminal outcome to database and compute summary totals."""
    db, _, _, wf = _get_execution_context(config)
    workflow_id_str = state.get("workflow_id")
    errors = state.get("errors", [])
    cancelled = state.get("cancelled", False)

    agents_run = state.get("agents_run", [])
    failed_agents = [a for a in agents_run if a.get("status") == "failed"]
    status = "completed"
    if cancelled:
        status = "cancelled"
    elif failed_agents and len(failed_agents) == len(agents_run):
        status = "failed"
    elif failed_agents:
        status = "partial"

    # Compute totals
    totals = {
        "opportunities_created": sum(a.get("opportunities_created", 0) for a in agents_run) or len(state.get("opportunities", [])),
        "actions_proposed": sum(a.get("actions_proposed", 0) for a in agents_run) or len(state.get("actions_proposed", [])),
        "signals_detected": sum(a.get("signals_detected", 0) for a in agents_run),
        "insights_generated": sum(a.get("insights_generated", 0) for a in agents_run),
        "experiments_proposed": sum(a.get("experiments_proposed", 0) for a in agents_run),
        "failed_agents": len(failed_agents),
        "reused_steps": sum(1 for a in agents_run if a.get("reused")),
        "agents_completed": sum(1 for a in agents_run if a.get("status") == "completed"),
    }

    if db and workflow_id_str and wf:
        try:
            workflow_id = uuid.UUID(workflow_id_str)
            generation = state.get("generation", 1)
            wf_row = db.get(AgentWorkflowRun, workflow_id)
            if wf_row:
                wf.finish_workflow(
                    wf_row,
                    status=status,
                    expected_generation=generation,
                )
                db.commit()
        except Exception as e:
            log.warning("Could not update AgentWorkflowRun in finalize_workflow_node: %s", e)
            try:
                db.rollback()
            except Exception:
                pass

    return {
        "status": status,
        "totals": totals,
        "terminal_outcome": {
            "status": status,
            "totals": totals,
            "errors": errors,
        },
    }
