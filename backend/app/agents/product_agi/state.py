"""Product Agent state machine — the nine-stage autonomous cycle.

    UNDERSTAND_CATALOG -> ANALYZE_PERFORMANCE -> FIND_OPPORTUNITIES
    -> RESEARCH_ANALYZE -> PREPARE_RECOMMENDATION -> SAFETY_CHECK
    -> WAITING_APPROVAL -> EXECUTE_MEASURE -> LEARN

Stage transitions are enforced by a finite state machine, so the agent can
never skip safety verification or wander out of order. Run-level status is
separate from the stage: a run can be ``running`` while its stage is
``ANALYZE_PERFORMANCE``, which is what the dashboard renders.

TERMINAL HONESTY
----------------
Two statuses matter for the acceptance contract and both are reachable
from real data:

  ``waiting_approval``            a recommendation became an approval-gated
                                 action and is parked for a human
  ``completed_no_actions``        the analysis ran, found real signal, but
                                 nothing needs a human to unblock it

A run never claims success it did not achieve. ``status`` is derived from
what actually happened, not from the stage it stopped in.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    approved_awaiting_execution = "approved_awaiting_execution"
    executing = "executing"
    completed = "completed"
    completed_no_actions = "completed_no_actions"
    completed_with_failures = "completed_with_failures"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"


class Stage(str, Enum):
    understand_catalog = "understand_catalog"
    analyze_performance = "analyze_performance"
    find_opportunities = "find_opportunities"
    research_analyze = "research_analyze"
    prepare_recommendation = "prepare_recommendation"
    safety_check = "safety_check"
    waiting_approval = "waiting_approval"
    execute_measure = "execute_measure"
    learn = "learn"


#: Ordered stages. The dashboard's eight visible steps are the first eight;
#: ``LEARN`` is a terminal bookkeeping stage.
STAGE_ORDER: list[Stage] = [
    Stage.understand_catalog,
    Stage.analyze_performance,
    Stage.find_opportunities,
    Stage.research_analyze,
    Stage.prepare_recommendation,
    Stage.safety_check,
    Stage.waiting_approval,
    Stage.execute_measure,
    Stage.learn,
]

#: The eight progress steps the workstation renders, in order.
PROGRESS_STEPS: tuple[tuple[str, str], ...] = (
    ("Understand", "catalog"),
    ("Analyze", "performance"),
    ("Find", "opportunities"),
    ("Research", "& analyze"),
    ("Prepare", "recommendation"),
    ("Safety", "check"),
    ("Waiting for", "approval"),
    ("Execute", "& measure"),
)

STAGE_TO_STEP_INDEX: dict[str, int] = {
    Stage.understand_catalog.value: 0,
    Stage.analyze_performance.value: 1,
    Stage.find_opportunities.value: 2,
    Stage.research_analyze.value: 3,
    Stage.prepare_recommendation.value: 4,
    Stage.safety_check.value: 5,
    Stage.waiting_approval.value: 6,
    Stage.execute_measure.value: 7,
    Stage.learn.value: 7,
}

#: Legal forward stage transitions. Each stage may only advance to the next
#: one, or terminate into WAITING_APPROVAL when the cycle stops for a human.
STAGE_TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.understand_catalog: {Stage.analyze_performance, Stage.waiting_approval},
    Stage.analyze_performance: {Stage.find_opportunities, Stage.waiting_approval},
    Stage.find_opportunities: {Stage.research_analyze, Stage.waiting_approval},
    Stage.research_analyze: {Stage.prepare_recommendation, Stage.waiting_approval},
    Stage.prepare_recommendation: {Stage.safety_check, Stage.waiting_approval},
    Stage.safety_check: {Stage.waiting_approval, Stage.execute_measure},
    Stage.waiting_approval: {Stage.execute_measure, Stage.learn},
    Stage.execute_measure: {Stage.learn},
    Stage.learn: set(),
}

RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.queued: {RunStatus.running, RunStatus.cancelled},
    RunStatus.running: {
        RunStatus.waiting_approval,
        RunStatus.completed_no_actions,
        RunStatus.blocked,
        RunStatus.failed,
        RunStatus.cancelled,
    },
    RunStatus.waiting_approval: {
        RunStatus.approved_awaiting_execution,
        RunStatus.completed_no_actions,
        RunStatus.blocked,
        RunStatus.failed,
        RunStatus.cancelled,
    },
    RunStatus.approved_awaiting_execution: {
        RunStatus.executing,
        RunStatus.waiting_approval,
        RunStatus.blocked,
        RunStatus.failed,
        RunStatus.cancelled,
    },
    RunStatus.executing: {
        RunStatus.completed,
        RunStatus.completed_with_failures,
        RunStatus.failed,
        RunStatus.cancelled,
    },
    RunStatus.blocked: {RunStatus.running, RunStatus.cancelled},
    RunStatus.completed_no_actions: set(),
    RunStatus.completed: set(),
    RunStatus.completed_with_failures: set(),
    RunStatus.failed: set(),
    RunStatus.cancelled: set(),
}


class StateTransitionError(Exception):
    """Raised on an illegal stage or run transition."""


def assert_stage_transition(current: str | Stage, target: str | Stage) -> None:
    cur = Stage(current)
    tgt = Stage(target)
    if tgt not in STAGE_TRANSITIONS[cur]:
        raise StateTransitionError(
            f"Illegal Product Agent stage transition: {cur.value} -> {tgt.value}"
        )


def assert_run_transition(current: str | RunStatus, target: str | RunStatus) -> None:
    cur = RunStatus(current)
    tgt = RunStatus(target)
    if tgt not in RUN_TRANSITIONS[cur]:
        raise StateTransitionError(
            f"Illegal Product Agent run transition: {cur.value} -> {tgt.value}"
        )


def stage_index(stage: str | Stage | None) -> int:
    """0-based index of a stage, or -1 when it is not on the visible track."""
    if stage is None:
        return -1
    return STAGE_TO_STEP_INDEX.get(Stage(stage).value, -1)


# ---------------------------------------------------------------------------
# Evidence + findings
# ---------------------------------------------------------------------------


@dataclass
class EvidenceItem:
    """One traceable statement.

    ``tool`` is the MCP tool that produced the statement, so any claim on
    the dashboard resolves back to a recorded MCP call. Nothing here is
    ever model-authored prose presented as a fact.
    """

    source: str
    source_kind: str          # mcp | rag | deterministic | llm
    statement: str
    tool: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_kind": self.source_kind,
            "statement": self.statement,
            "tool": self.tool,
            "data": self.data,
        }


#: Impact text used whenever no real impact can be calculated. One constant
#: so the dashboard and the API never disagree about what "unavailable" means.
IMPACT_UNAVAILABLE_REASON = (
    "Impact estimate unavailable — insufficient historical data to calculate it."
)

#: Impact text used when an action is genuinely required but no measurable
#: outcome exists yet.
IMPACT_PENDING_REASON = (
    "Impact cannot be measured yet — this recommendation has not been approved "
    "and executed, so no outcome exists."
)


@dataclass
class ProductAgentState:
    """Everything the agent knows, concluded and produced this run."""

    # identity
    run_id: str
    merchant_id: str
    objective: str
    stage: Stage = Stage.understand_catalog
    #: Trailing lookback window in days every measurement uses. Set once from
    #: the run's own configuration so the catalog view, the performance view
    #: and the dashboard can never disagree about what period they describe.
    window_days: int = 90

    # ── observation (all measured, never modelled) ──────────────────────
    catalog: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    opportunities: dict[str, Any] = field(default_factory=dict)
    opportunities_payload: dict[str, Any] = field(default_factory=dict)

    # ── research ─────────────────────────────────────────────────────────
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    retrieval_log: list[dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    rag_rounds: int = 0

    # ── conclusion ───────────────────────────────────────────────────────
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    prepared_actions: list[dict[str, Any]] = field(default_factory=list)

    # ── learning ─────────────────────────────────────────────────────────
    learned: list[dict[str, Any]] = field(default_factory=list)
    learning_status: str = "not_started"  # not_started | pending_outcomes

    # ── observability ────────────────────────────────────────────────────
    mcp_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    llm_decisions: list[dict[str, Any]] = field(default_factory=list)
    llm_degraded: bool = False
    reasoning_status: str = "idle"
    current_decision: str | None = None
    reasoning_summary: str | None = None

    # ── loop control ─────────────────────────────────────────────────────
    iterations: int = 0
    tool_call_count: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    timing: dict[str, Any] = field(
        default_factory=lambda: {
            "total_ms": 0,
            "llm_total_ms": 0,
            "mcp_total_ms": 0,
            "rag_total_ms": 0,
            "db_total_ms": 0,
            "analysis_total_ms": 0,
            "llm_calls": 0,
            "rag_rounds": 0,
            "mcp_calls": 0,
            "mcp_cache_hits": 0,
            "mcp_errors": 0,
            "mcp_retries": 0,
            "tool_calls": 0,
        }
    )

    # ── helpers ──────────────────────────────────────────────────────────

    def add_evidence(
        self,
        source: str,
        kind: str,
        statement: str,
        *,
        tool: str | None = None,
        **data: Any,
    ) -> None:
        self.evidence.append(
            EvidenceItem(
                source=source, source_kind=kind, statement=statement, tool=tool, data=data
            )
        )

    def evidence_payload(self, limit: int = 8) -> list[dict[str, Any]]:
        """Safe evidence projection for a persisted row."""
        return [
            {
                "source": e.source,
                "source_kind": e.source_kind,
                "statement": e.statement,
                "tool": e.tool,
            }
            for e in self.evidence[:limit]
        ]

    def set_stage(self, stage: Stage) -> None:
        if self.stage != stage and stage not in STAGE_TRANSITIONS[self.stage]:
            raise StateTransitionError(
                f"Illegal Product Agent stage transition: "
                f"{self.stage.value} -> {stage.value}"
            )
        self.stage = stage

    def progress_step(self) -> int:
        return stage_index(self.stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "merchant_id": self.merchant_id,
            "objective": self.objective,
            "stage": self.stage.value,
            "window_days": self.window_days,
            "catalog": self.catalog,
            "performance": self.performance,
            "opportunities": self.opportunities,
            "opportunities_payload": self.opportunities_payload,
            "findings": self.findings,
            "evidence": [e.to_dict() for e in self.evidence],
            "retrieval_log": self.retrieval_log,
            "knowledge_gaps": self.knowledge_gaps,
            "rag_rounds": self.rag_rounds,
            "recommendations": self.recommendations,
            "verification": self.verification,
            "prepared_actions": self.prepared_actions,
            "learned": self.learned,
            "learning_status": self.learning_status,
            "mcp_calls": self.mcp_calls,
            "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
            "llm_decisions": self.llm_decisions,
            "llm_degraded": self.llm_degraded,
            "reasoning_status": self.reasoning_status,
            "current_decision": self.current_decision,
            "reasoning_summary": self.reasoning_summary,
            "iterations": self.iterations,
            "tool_call_count": self.tool_call_count,
            "cancelled": self.cancelled,
            "errors": self.errors,
            "timing": self.timing,
        }


def new_merchant_tenant(db: Any, merchant_id: uuid.UUID | None) -> str | None:
    """Serialize a tenant id for state payloads (never a credential)."""
    return str(merchant_id) if merchant_id else None


__all__ = [
    "IMPACT_PENDING_REASON",
    "IMPACT_UNAVAILABLE_REASON",
    "PROGRESS_STEPS",
    "RUN_TRANSITIONS",
    "STAGE_ORDER",
    "STAGE_TO_STEP_INDEX",
    "STAGE_TRANSITIONS",
    "EvidenceItem",
    "ProductAgentState",
    "RunStatus",
    "Stage",
    "StateTransitionError",
    "assert_run_transition",
    "assert_stage_transition",
    "stage_index",
    "utcnow",
]