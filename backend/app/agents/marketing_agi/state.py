"""MarketingAGI state machine — the structured brain of the agent.

Every autonomous run maintains explicit, serializable state covering
what the agent knows, what it doesn't, what it's investigating, what it
has concluded, and what it has produced. State transitions are enforced
by a finite state machine so the agent can never wander.

Top-level run statuses (persisted on MarketingAGIRun):

    queued -> running -> waiting_approval | completed | blocked | failed
                                        -> cancelled (external cancel)

Phases (MarketingAGIRun.phase):

    load_context -> observe -> investigate -> plan -> create -> verify
    -> prepare -> awaiting_approval
"""
from __future__ import annotations

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
    completed = "completed"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"


class Phase(str, Enum):
    load_context = "load_context"
    observe = "observe"
    investigate = "investigate"
    plan = "plan"
    create = "create"
    verify = "verify"
    prepare = "prepare"
    awaiting_approval = "awaiting_approval"
    complete = "complete"


# Legal forward transitions of the run-level FSM.
RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.queued: {RunStatus.running, RunStatus.cancelled},
    RunStatus.running: {
        RunStatus.waiting_approval,
        RunStatus.completed,
        RunStatus.blocked,
        RunStatus.failed,
        RunStatus.cancelled,
    },
    RunStatus.waiting_approval: {
        RunStatus.completed,
        RunStatus.blocked,
        RunStatus.cancelled,
    },
    RunStatus.blocked: {RunStatus.running, RunStatus.cancelled},
    # terminal
    RunStatus.completed: set(),
    RunStatus.failed: set(),
    RunStatus.cancelled: set(),
}

PHASE_ORDER: list[Phase] = [
    Phase.load_context,
    Phase.observe,
    Phase.investigate,
    Phase.plan,
    Phase.create,
    Phase.verify,
    Phase.prepare,
    Phase.awaiting_approval,
    Phase.complete,
]


class StateTransitionError(Exception):
    """Raised on an illegal FSM transition."""


def assert_run_transition(current: str | RunStatus, target: str | RunStatus) -> None:
    cur = RunStatus(current)
    tgt = RunStatus(target)
    if tgt not in RUN_TRANSITIONS[cur]:
        raise StateTransitionError(
            f"Illegal MarketingAGI run transition: {cur.value} -> {tgt.value}"
        )


# ---------------------------------------------------------------------------
# Structured hypothesis record
# ---------------------------------------------------------------------------


@dataclass
class Hypothesis:
    statement: str
    confidence: float = 0.5
    status: str = "open"  # open | confirmed | rejected | insufficient_evidence
    supporting_evidence: list[str] = field(default_factory=list)
    opposing_evidence: list[str] = field(default_factory=list)
    next_investigation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "supporting_evidence": self.supporting_evidence,
            "opposing_evidence": self.opposing_evidence,
            "next_investigation": self.next_investigation,
        }


# ---------------------------------------------------------------------------
# Evidence record — every important conclusion must trace to evidence
# ---------------------------------------------------------------------------


@dataclass
class EvidenceItem:
    source: str          # tool name / retrieval source type
    source_kind: str     # sql | retrieval | memory | integration
    statement: str       # factual statement this evidence supports
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_kind": self.source_kind,
            "statement": self.statement,
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# The Marketing AGI brain state
# ---------------------------------------------------------------------------


@dataclass
class MarketingAGIState:
    """Everything the agent knows, is doing, and has produced this run."""

    # identity
    run_id: str
    merchant_id: str
    objective: str

    # context
    business_context: dict[str, Any] = field(default_factory=dict)
    customer_context: dict[str, Any] = field(default_factory=dict)
    marketing_context: dict[str, Any] = field(default_factory=dict)
    memory_context: list[dict[str, Any]] = field(default_factory=list)

    # research
    observations: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    retrieval_log: list[dict[str, Any]] = field(default_factory=list)

    # tool usage
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)

    # plan
    plan: list[dict[str, Any]] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    workflow: str | None = None

    # output
    campaign_draft: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    prepared_action: dict[str, Any] | None = None

    # learning
    learned_insights: list[str] = field(default_factory=list)

    # loop control
    iterations: int = 0
    tool_call_count: int = 0
    duplicate_tool_calls: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    # ── helpers ──────────────────────────────────────────────────────────

    def add_evidence(self, source: str, kind: str, statement: str, **data: Any) -> None:
        self.evidence.append(
            EvidenceItem(source=source, source_kind=kind, statement=statement, data=data)
        )

    def add_hypothesis(self, statement: str, confidence: float = 0.5) -> Hypothesis:
        h = Hypothesis(statement=statement, confidence=confidence)
        self.hypotheses.append(h)
        return h

    def seen_tool_calls(self) -> set[tuple[str, str]]:
        """Fingerprint set for duplicate tool-call prevention."""
        return {
            (c.get("tool", ""), _stable_kw(c.get("params", {})))
            for c in self.tool_calls
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "merchant_id": self.merchant_id,
            "objective": self.objective,
            "business_context": self.business_context,
            "customer_context": self.customer_context,
            "marketing_context": self.marketing_context,
            "memory_context": self.memory_context,
            "observations": self.observations,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence": [e.to_dict() for e in self.evidence],
            "knowledge_gaps": self.knowledge_gaps,
            "retrieval_log": self.retrieval_log,
            "tool_calls": self.tool_calls,
            "selected_tools": self.selected_tools,
            "plan": self.plan,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "current_step": self.current_step,
            "workflow": self.workflow,
            "campaign_draft": self.campaign_draft,
            "verification": self.verification,
            "prepared_action": self.prepared_action,
            "learned_insights": self.learned_insights,
            "iterations": self.iterations,
            "tool_call_count": self.tool_call_count,
            "duplicate_tool_calls": self.duplicate_tool_calls,
            "cancelled": self.cancelled,
            "errors": self.errors,
        }


def _stable_kw(params: dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(params, sort_keys=True, default=str)
    except Exception:
        return repr(params)
