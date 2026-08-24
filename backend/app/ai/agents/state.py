"""
Agent state — tracks the full lifecycle of one agentic analysis run.

Stores:
  - goal
  - tool calls and their results (concise summaries, not raw chain-of-thought)
  - retrieved evidence items
  - final insights
  - errors

Does NOT store raw LLM chain-of-thought — only concise evidence summaries
that are safe to expose in audit logs and API responses.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.ai.rag.context import RetrievedItem


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool_name: str
    params: dict[str, Any]
    result_summary: str       # Concise human-readable summary — NOT raw output
    item_count: int = 0
    step: int = 0


@dataclass
class AgentState:
    """
    Mutable state for one agentic analysis run.

    Created at the start of each run and passed through the agent loop.
    Immutable once the run completes.
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    merchant_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    # Retrieval tracking
    tool_calls: list[ToolCall] = field(default_factory=list)
    retrieved_evidence: list[RetrievedItem] = field(default_factory=list)
    retrieval_steps_used: int = 0

    # Final output
    insights: list[dict[str, Any]] = field(default_factory=list)
    insufficient_evidence: bool = False
    evidence_summary: str = ""
    status: str = "running"   # running | completed | failed | insufficient_evidence
    error: str | None = None

    def record_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        result_summary: str,
        item_count: int,
    ) -> None:
        self.tool_calls.append(
            ToolCall(
                tool_name=tool_name,
                params=params,
                result_summary=result_summary,
                item_count=item_count,
                step=self.retrieval_steps_used,
            )
        )

    def add_evidence(self, items: list[RetrievedItem]) -> None:
        self.retrieved_evidence.extend(items)

    def complete(self, insights: list[dict], evidence_summary: str) -> None:
        self.insights = insights
        self.evidence_summary = evidence_summary
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)

    def fail(self, error: str) -> None:
        self.error = error
        self.status = "failed"
        self.completed_at = datetime.now(timezone.utc)

    def mark_insufficient(self, summary: str) -> None:
        self.insufficient_evidence = True
        self.evidence_summary = summary
        self.status = "insufficient_evidence"
        self.completed_at = datetime.now(timezone.utc)

    def to_api_response(self) -> dict[str, Any]:
        """Serialise to the shape returned by POST /api/ai/analyze."""
        return {
            "analysis_id": self.run_id,
            "status": self.status,
            "goal": self.goal,
            "insights": self.insights,
            "evidence_summary": self.evidence_summary,
            "retrieval_steps": self.retrieval_steps_used,
            "tool_calls": [
                {
                    "step": tc.step,
                    "tool": tc.tool_name,
                    "result_summary": tc.result_summary,
                    "items_retrieved": tc.item_count,
                }
                for tc in self.tool_calls
            ],
            "insufficient_evidence": self.insufficient_evidence,
            "error": self.error,
        }
