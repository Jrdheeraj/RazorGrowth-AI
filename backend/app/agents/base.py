"""Base agent infrastructure — Phase 5 Features 1, 13, 14.

Every specialised agent:
   - has a clear responsibility (one per agent),
   - receives structured input (AgentContext),
   - returns structured output (AgentResult),
   - is restricted by the permission registry,
   - never raises past its boundary (execute() converts failures into
     structured failed results so one agent cannot crash the system),
   - records which internal tools it used and how long each layer took,
   - follows a bounded autonomous execution lifecycle:
     GOAL → CONTEXT GATHERING → PLAN → TOOL SELECTION → TOOL EXECUTION
     → OBSERVATION → EVALUATION → REPLAN IF NECESSARY → PERSIST FINDINGS
     → HANDOFF OR COMPLETE → LEARN FROM OUTCOME.
"""
from __future__ import annotations

import logging
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.agents.permissions import (
    PROPOSE_ACTION,
    SIMULATE,
    AgentPermissionError,
    assert_permission,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a persisted-id string back to a UUID, or None."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


# ── AgentContext ──────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Structured input handed to every agent run."""

    db: Session
    merchant_id: uuid.UUID
    mode: str = "deep"                      # fast | deep
    params: dict[str, Any] = field(default_factory=dict)
    llm: Any = None                         # BaseLLMProvider | None
    embedding_provider: Any = None          # BaseEmbeddingProvider | None
    shared: dict[str, Any] = field(default_factory=dict)  # cross-agent scratchpad


# ── AgentResult ───────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Structured output produced by every agent run."""

    agent_name: str
    status: str = "completed"               # completed | failed | skipped | blocked | replan_required
    opportunities_created: int = 0
    actions_proposed: int = 0
    insights_generated: int = 0
    signals_detected: int = 0
    experiments_proposed: int = 0
    memories_written: int = 0
    tools_used: list[str] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    total_ms: int = 0
    llm_ms: int = 0
    db_ms: int = 0
    tool_ms: int = 0
    # Lifecycle tracking
    lifecycle_phases: list[dict[str, Any]] = field(default_factory=list)
    evaluation_result: dict[str, Any] | None = None
    replan_trigger: str | None = None  # reason for replan, if any
    handoff_id: str | None = None
    persist_flag: bool = False

    @property
    def ok(self) -> bool:
        return self.status in ("completed", "partially_completed")


# ── BaseGrowthAgent ──────────────────────────────────────────────────

class BaseGrowthAgent(ABC):
    """Abstract specialised agent.

    Subclasses implement _run(ctx, result) and MUST declare NAME + PERMISSIONS.
    All capability-gated helpers route through assert_permission so an
    agent physically cannot act outside its declared powers.

    The execute() method follows a bounded autonomous execution lifecycle:
    GOAL → CONTEXT GATHERING → PLAN → TOOL SELECTION → TOOL EXECUTION
    → OBSERVATION → EVALUATION → REPLAN IF NECESSARY → PERSIST FINDINGS
    → HANDOFF OR COMPLETE → LEARN FROM OUTCOME.

    Configurable limits prevent infinite loops:
    - max_steps: maximum lifecycle iterations (default 5)
    - max_retries: maximum transient failure retries (default 3)
    - max_replan: maximum replan attempts (default 2)
    """

    NAME: str = ""
    DESCRIPTION: str = ""
    PERMISSIONS: frozenset[str] = frozenset()
    TOOLS: tuple[str, ...] = ()

    # ── lifecycle configuration ───────────────────────────────────────

    max_steps: int = 5          # maximum full lifecycle iterations
    max_retries: int = 3        # maximum transient failure retries
    max_replan: int = 2         # maximum replan attempts within one run

    #: Cycle id for the workflow currently executing this agent, set by
    #: execute(). Scopes Phase 4 proposal idempotency to one cycle. Declared
    #: here (not per-run) because agents are long-lived registry singletons.
    _workflow_run_id: uuid.UUID | None = None

    def get_langchain_adapter(self, ctx: AgentContext) -> Any:
        """Retrieve or construct the LangChainAgentAdapter for this agent."""
        adapter = ctx.shared.get("langchain_adapter")
        if adapter is not None and getattr(adapter, "agent_name", None) == self.NAME:
            return adapter
        from backend.app.ai.langchain_adapter.adapter import LangChainAgentAdapter

        new_adapter = LangChainAgentAdapter(
            agent_name=self.NAME,
            db=ctx.db,
            merchant_id=ctx.merchant_id,
            llm=ctx.llm,
        )
        ctx.shared["langchain_adapter"] = new_adapter
        return new_adapter

    def get_langchain_tools(self, ctx: AgentContext) -> list[Any]:
        """Retrieve authorized LangChain BaseTool instances for this agent."""
        return self.get_langchain_adapter(ctx).tools

    # ── public entry point (never raises) ─────────────────────────────

    def execute(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        result = AgentResult(
            agent_name=self.NAME,
            tools_used=list(self.TOOLS),
            lifecycle_phases=[],
        )
        rag_context = ctx.shared.get("rag_context")
        result.output["objective"] = ctx.params.get("objective")
        # Stash the cycle id so a Phase 4 proposal can be idempotency-scoped to
        # this workflow. A step executed outside a workflow leaves it None and
        # keeps the previous, unscoped behaviour.
        self._workflow_run_id = _uuid_or_none(ctx.params.get("workflow_run_id"))
        if rag_context:
            result.output["evidence_context"] = {
                "status": rag_context.get("status"),
                "merchant_id": rag_context.get("merchant_id"),
                "verified_facts": rag_context.get("verified_facts", []),
                "derived_metrics": rag_context.get("derived_metrics", {}),
                "retrieved_context": rag_context.get("retrieved_context", []),
                "data_sufficiency": rag_context.get("data_sufficiency", {}),
            }
        try:
            if (
                rag_context
                and rag_context.get("status") == "insufficient_data"
                and ctx.mode == "growth_team"
                and self.NAME != "ManagerAgent"
            ):
                result.output["decision"] = "INSUFFICIENT EVIDENCE"
                result.output["recommendation"] = None
                result.status = "completed"
                result.lifecycle_phases.append(
                    {"phase": "goal_set", "entered_at": _utcnow().isoformat(), "outcome": "blocked"}
                )
                return result
            else:
                self._execute_lifecycle(ctx, result)
            # Never launder a recorded failure into a success. An agent that
            # detected its own failure inside _run (e.g. the Designer Agent
            # when the LLM provider refused) must keep the honest status.
            if result.status not in ("failed", "blocked", "replan_required"):
                result.status = "completed"
        except AgentPermissionError as exc:
            log.error("Permission violation in %s: %s", self.NAME, exc)
            result.status = "failed"
            result.errors.append(f"PERMISSION_DENIED: {exc}")
        except Exception as exc:  # noqa: BLE001 — failure isolation boundary
            log.exception("Agent %s failed", self.NAME)
            result.status = "failed"
            result.errors.append(f"{type(exc).__name__}: {exc}")
        result.total_ms = int((time.perf_counter() - t0) * 1000)
        # Ensure lifecycle phases are recorded even on failure
        if not result.lifecycle_phases:
            result.lifecycle_phases.append(
                {"phase": "goal_set", "outcome": result.status}
            )
        return result

    def _execute_lifecycle(self, ctx: AgentContext, result: AgentResult) -> None:
        """Run the bounded autonomous execution lifecycle around _core_work."""

        objectives = ctx.params.get("objective", "Growth analysis and optimization")

        # Record goal set phase
        result.lifecycle_phases.append(
            {"phase": "goal_set", "objective": objectives, "entered_at": _utcnow().isoformat()}
        )

        # Run the agent's core work (_run) within the lifecycle framework
        # with bounded retries and replan logic
        for attempt in range(self.max_steps + 1):
            # At the start of each attempt, record context_gathering phase
            if attempt > 0:
                result.lifecycle_phases.append(
                    {"phase": "context_gathering", "attempt": attempt, "entered_at": _utcnow().isoformat()}
                )

            # PLAN - agent's _run does the planning inherently
            result.lifecycle_phases.append(
                {"phase": "planning", "attempt": attempt, "entered_at": _utcnow().isoformat()}
            )

            # Execute the agent's core work
            try:
                self._run(ctx, result)
                # If _run completed without setting a non-completed status,
                # mark as completed at the end
                if result.status in ("completed", "partially_completed", "replan_required"):
                    break
                # If _run set status to failed, evaluate whether we should replan
            except AgentPermissionError as exc:
                log.error("Permission violation in %s: %s", self.NAME, exc)
                result.status = "failed"
                result.errors.append(f"PERMISSION_DENIED: {exc}")
                break
            except Exception as exc:  # noqa: BLE001 — failure isolation boundary
                log.exception("Agent %s failed on attempt %d", self.NAME, attempt)
                result.status = "failed"
                result.errors.append(f"{type(exc).__name__}: {exc}")
                # Transient failures: retry if under max_retries
                if attempt < self.max_retries:
                    continue
                break

        # If we exhausted attempts and status is still completed/partial, persist findings
        if result.status in ("completed", "partially_completed"):
            result.lifecycle_phases.append(
                {"phase": "persist_findings", "outcome": result.status, "entered_at": _utcnow().isoformat()}
            )
            result.persist_flag = True
            return
        # If replan_required or failed, check if we should replan
        if result.status == "replan_required" and attempt < self.max_replan:
            result.lifecycle_phases.append(
                {"phase": "replan", "trigger": result.replan_trigger, "attempt": attempt, "outcome": "will_replan", "entered_at": _utcnow().isoformat()}
            )
            # Reset status to running-like so the orchestrator can restart
            result.status = "running"
            return
        # Failed or max_replan reached
        if result.status == "failed" or result.status == "replan_required":
            result.lifecycle_phases.append(
                {"phase": "persist_findings", "outcome": result.status, "entered_at": _utcnow().isoformat()}
            )
            result.persist_flag = True

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        """Do the agent's specialised work. Populate `result`.

        Subclasses MUST implement this. This is the core business logic.
        The base implementation sets a note that no work was defined.
        """

        result.output["note"] = "No agent work defined - subclass must implement _run"

    # ── capability-gated helpers ───────────────────────────────────────

    def _require(self, capability: str) -> None:
        assert_permission(self.NAME, capability)

    def _simulate(self, engine: Any, scenario_type: str, **kwargs: Any) -> Any:
        """Run a what-if scenario (requires SIMULATE permission)."""
        self._require(SIMULATE)
        t0 = time.perf_counter()
        out = engine.simulate(scenario_type, **kwargs)
        setattr(self, "_last_tool_ms", int((time.perf_counter() - t0) * 1000))
        return out

    def _propose_phase4_action(
        self,
        action_service: Any,
        *,
        db: Session,
        merchant_id: uuid.UUID,
        action_type: str,
        payload: dict[str, Any],
    ) -> Any:
        """
        Create a Phase 4 AgentAction in 'requested' state.

        This is the ONLY sanctioned bridge between agents and execution:
        the resulting action still faces both guardrail evaluations and a
        mandatory human approval before anything happens. Agents can
        propose; only humans can approve.

        The proposal is idempotent within its workflow cycle. A retried or
        resumed step re-proposing the same action returns the EXISTING row
        instead of filling the merchant's queue with a duplicate -- which is
        the failure the crash-recovery test observed. The key is derived
        deterministically from (merchant, type, payload, workflow), so a
        genuinely new proposal still creates a new row.
        """
        self._require(PROPOSE_ACTION)
        t0 = time.perf_counter()
        action = action_service.create_action(
            db,
            merchant_id=merchant_id,
            action_type=action_type,
            input_payload=payload,
            requested_by=f"agent:{self.NAME}",
            idempotency_key=self._action_idempotency_key(
                merchant_id=merchant_id,
                action_type=action_type,
                payload=payload,
            ),
        )
        self._last_tool_ms = int((time.perf_counter() - t0) * 1000)
        return action

    def _action_idempotency_key(
        self,
        *,
        merchant_id: uuid.UUID,
        action_type: str,
        payload: dict[str, Any],
    ) -> str:
        """
        Idempotency key for one proposal inside the current workflow cycle.

        Scoped to the cycle when the orchestrator stamped one, so two separate
        analyses of the same merchant may each legitimately raise the same
        proposal, while a retry WITHIN a cycle does not duplicate it.
        """
        from backend.app.services.action_service import action_idempotency_key

        workflow_run_id = self._workflow_run_id
        return action_idempotency_key(
            merchant_id=merchant_id,
            action_type=action_type,
            input_payload=payload,
            workflow_run_id=workflow_run_id,
        )

    @staticmethod
    def _timed(fn, *args, **kwargs):
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, int((time.perf_counter() - t0) * 1000)

    def _generate_debate_message(
        self,
        ctx: AgentContext,
        result: AgentResult,
        *,
        agent_label: str,
        phase: str,
        objective: str,
        evidence: dict[str, Any],
        instruction: str,
        fallback: str,
    ) -> str:
        """Generate one merchant-facing debate message from grounded evidence."""
        if ctx.llm is None:
            result.errors.append("llm_not_configured")
            return fallback

        system_prompt = (
            "You are a specialist in a concise business debate for a merchant. "
            "Use only the supplied evidence. Do not invent numbers, customers, "
            "orders, payments, products, revenue, or API details. Write as the "
            f"{agent_label}. Mention agreement, disagreement, challenge, or "
            "refinement when the phase calls for it. Keep it to 2-4 sentences "
            "in plain business English."
        )
        user_prompt = json.dumps(
            {
                "agent": agent_label,
                "phase": phase,
                "objective": objective,
                "evidence": evidence,
                "instruction": instruction,
            },
            default=str,
            indent=2,
        )
        adapter = self.get_langchain_adapter(ctx)
        generated, llm_ms = adapter.execute_text_reasoning(
            system_instruction=system_prompt,
            user_instruction=user_prompt,
            temperature=0.35,
        )
        result.llm_ms += llm_ms
        content = generated.strip()
        if not content:
            raise RuntimeError("LLM_ANALYSIS_EMPTY")
        return content