"""
Focused regression tests for ``debate_id`` / ``action_plan`` propagation.

THE DEFECT
----------
The LangGraph step executor never published cycle-level results into graph
state, so ``OrchestrationSummary`` came back with ``debate_id=None`` and
``action_plan=None`` even when the Manager had created a real AgentDebate row
or coordinated a real action plan. The step-reuse branch had the same gap: a
resumed cycle whose Manager step was replayed lost the persisted results, so
downstream agents also lost the Manager's delegations.

WHAT IS PROVEN HERE
-------------------
1. A full LangGraph ``team`` run returns the real, persisted action plan.
2. A full LangGraph ``growth_team`` run returns the real debate row's id.
3. Neither value is invented when the Manager produced neither.
4. Replaying a persisted Manager step restores both values (and delegations)
   into graph state, using the persisted output as the only source.
5. The legacy executor's results are unchanged (backward compatibility).
"""
from __future__ import annotations

import uuid

import pytest

from backend.app.agents.base import AgentResult
from backend.app.agents.orchestrator import (
    AI_TEAM_PLAN,
    GrowthAgentOrchestrator,
)
from backend.app.ai.langgraph_orchestrator.nodes import _execute_agent_step
from backend.app.models.agent_debate import AgentDebate
from backend.app.models.agent_run import AgentRun
from backend.app.services.agent_run_service import AgentRunService
from backend.app.services.workflow_run_service import (
    EXECUTION_ENGINE_LANGGRAPH,
    WorkflowRunService,
    step_key,
)
from tests.security_utils import make_world

TEAM_MANAGER_INDEX = 13  # AI_TEAM_PLAN: ("ManagerAgent", {"phase": "coordinate"})
TEAM_MANAGER_PHASE = "coordinate"


@pytest.fixture()
def merchant(db_session):
    m, _u, _m = make_world(db_session, slug_hint="resultfields")
    return m


@pytest.fixture()
def isolated_checkpoints(tmp_path, monkeypatch):
    """Keep probe/run checkpoints out of the repository tree."""
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
    return tmp_path


def _manager_run(db_session, merchant, run_id):
    return (
        db_session.query(AgentRun)
        .filter(
            AgentRun.merchant_id == merchant.id,
            AgentRun.orchestrator_run_id == run_id,
            AgentRun.agent_name == "ManagerAgent",
        )
        .one()
    )


# ════════════════════════════════════════════════════════════════════════════
# 1-3. Full LangGraph runs
# ════════════════════════════════════════════════════════════════════════════


class TestTeamRunSurfacesTheRealActionPlan:
    def test_langgraph_team_run_returns_the_persisted_action_plan(
        self, db_session, merchant, isolated_checkpoints
    ):
        objective = f"regression action plan {uuid.uuid4().hex[:8]}"
        orch = GrowthAgentOrchestrator(db_session, llm=None, embedding_provider=None)

        summary = orch.run(
            merchant.id,
            mode="team",
            params={"objective": objective, "window_days": 30},
        )
        db_session.commit()

        assert summary.status in ("completed", "partial")
        assert isinstance(summary.action_plan, dict), (
            "a team run whose Manager coordinated a plan must return it"
        )
        assert summary.action_plan["objective"] == objective
        assert summary.action_plan["status"] == "ready_for_merchant_review"
        assert summary.action_plan["initiatives"], "the real plan must carry initiatives"
        # The AI Team workspace does not open a debate; nothing may invent one.
        assert summary.debate_id is None

        # The summary value is the Manager's PERSISTED output, not a new object.
        manager = _manager_run(db_session, merchant, summary.orchestrator_run_id)
        assert manager.step_index == TEAM_MANAGER_INDEX
        assert manager.output_summary["action_plan"] == summary.action_plan

        # The API-facing mapping carries the same value.
        assert summary.to_dict()["action_plan"] == summary.action_plan


class TestGrowthTeamRunSurfacesTheRealDebate:
    def test_langgraph_growth_team_run_returns_the_real_debate_id(
        self, db_session, merchant, isolated_checkpoints
    ):
        orch = GrowthAgentOrchestrator(db_session, llm=None, embedding_provider=None)

        summary = orch.run(
            merchant.id,
            mode="growth_team",
            params={"objective": "debate provenance regression", "window_days": 30},
        )
        db_session.commit()

        assert summary.status in ("completed", "partial")
        assert summary.debate_id, (
            "the Manager created a real debate; the summary must carry its id"
        )
        debate = db_session.get(AgentDebate, uuid.UUID(summary.debate_id))
        assert debate is not None, "the reported debate id must name a real row"
        assert debate.merchant_id == merchant.id

        # The reported id is exactly what the Manager persisted.
        manager = (
            db_session.query(AgentRun)
            .filter(
                AgentRun.merchant_id == merchant.id,
                AgentRun.orchestrator_run_id == summary.orchestrator_run_id,
                AgentRun.agent_name == "ManagerAgent",
                AgentRun.step_index == 1,  # the delegate step creates the debate
            )
            .one()
        )
        assert manager.output_summary["debate_id"] == summary.debate_id

        # The growth_team graph produces a debate, not an executive action
        # plan; absent output must stay absent rather than be fabricated.
        assert summary.action_plan is None
        assert summary.to_dict()["debate_id"] == summary.debate_id


# ════════════════════════════════════════════════════════════════════════════
# 4. Step reuse replays the persisted cycle-level results
# ════════════════════════════════════════════════════════════════════════════


class TestReusedManagerStepRestoresResults:
    def _persist_manager_step(self, db_session, merchant, run_id, output):
        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=run_id,
            mode="team",
            plan=AI_TEAM_PLAN,
            execution_engine=EXECUTION_ENGINE_LANGGRAPH,
        )
        db_session.commit()

        svc = AgentRunService(db_session)
        row = svc.start_run(
            merchant_id=merchant.id,
            agent_name="ManagerAgent",
            orchestrator_run_id=run_id,
            mode="team",
            workflow_id=workflow.id,
            step_key=step_key(
                "team", TEAM_MANAGER_INDEX, "ManagerAgent", TEAM_MANAGER_PHASE
            ),
            step_index=TEAM_MANAGER_INDEX,
            attempt=1,
        )
        result = AgentResult(agent_name="ManagerAgent", status="completed")
        result.output.update(output)
        svc.complete_run(row, result)
        db_session.commit()
        return workflow, row

    def _state(self, merchant, workflow, run_id):
        return {
            "merchant_id": str(merchant.id),
            "run_id": run_id,
            "workflow_id": str(workflow.id),
            "mode": "team",
            "params": {"objective": "reuse regression", "window_days": 30},
            "generation": 1,
            "current_step_index": TEAM_MANAGER_INDEX,
            "shared_memory": {},
        }

    def test_reuse_restores_debate_id_action_plan_and_delegations(
        self, db_session, merchant
    ):
        run_id = uuid.uuid4().hex
        debate_id = str(uuid.uuid4())
        delegations = [
            {"task_id": str(uuid.uuid4()), "assigned_to": "marketing"},
            {"task_id": str(uuid.uuid4()), "assigned_to": "product"},
        ]
        action_plan = {
            "objective": "reuse regression",
            "executive_summary": "persisted plan",
            "initiatives": [{"title": "persisted initiative"}],
            "status": "ready_for_merchant_review",
        }
        workflow, row = self._persist_manager_step(
            db_session,
            merchant,
            run_id,
            {
                "debate_id": debate_id,
                "delegations": delegations,
                "action_plan": action_plan,
            },
        )

        updates = _execute_agent_step(
            "ManagerAgent",
            self._state(merchant, workflow, run_id),
            {"configurable": {"db": db_session, "wf": WorkflowRunService(db_session)}},
            phase=TEAM_MANAGER_PHASE,
        )

        assert updates["agents_run"][0]["reused"] is True
        assert updates["agents_run"][0]["step_key"] == row.step_key
        assert updates["debate_id"] == debate_id
        assert updates["action_plan"] == action_plan
        # Downstream specialist steps read these from shared memory.
        assert updates["shared_memory"]["manager_debate_id"] == debate_id
        assert updates["shared_memory"]["manager_delegations"] == delegations
        db_session.rollback()

    def test_reuse_does_not_invent_results_the_manager_never_produced(
        self, db_session, merchant
    ):
        run_id = uuid.uuid4().hex
        workflow, _row = self._persist_manager_step(
            db_session, merchant, run_id, {"status": "coordinated"}
        )

        updates = _execute_agent_step(
            "ManagerAgent",
            self._state(merchant, workflow, run_id),
            {"configurable": {"db": db_session, "wf": WorkflowRunService(db_session)}},
            phase=TEAM_MANAGER_PHASE,
        )

        assert updates["agents_run"][0]["reused"] is True
        assert "debate_id" not in updates
        assert "action_plan" not in updates
        assert "shared_memory" not in updates
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 5. Legacy results are unchanged
# ════════════════════════════════════════════════════════════════════════════


class TestLegacyResultsUnchanged:
    def test_legacy_team_run_still_returns_the_action_plan(
        self, db_session, merchant, isolated_checkpoints
    ):
        objective = f"legacy action plan {uuid.uuid4().hex[:8]}"
        orch = GrowthAgentOrchestrator(db_session, llm=None, embedding_provider=None)

        summary = orch.run(
            merchant.id,
            mode="team",
            params={"objective": objective, "window_days": 30},
            run_id=uuid.uuid4().hex,
            use_langgraph=False,
        )
        db_session.commit()

        assert isinstance(summary.action_plan, dict)
        assert summary.action_plan["objective"] == objective
        assert summary.action_plan["status"] == "ready_for_merchant_review"
        assert summary.debate_id is None
