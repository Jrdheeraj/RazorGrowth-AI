"""
Typed workflow state for the shared LangGraph execution architecture.

Designed to contain only necessary execution, telemetry, and audit data,
strictly excluding raw credentials, secrets, or sensitive merchant tokens.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


def add_items(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Reducer that appends new items to an existing list."""
    base = list(left or [])
    if not right:
        return base
    return base + list(right)


def add_unique_strings(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Reducer that preserves uniqueness of strings."""
    res = list(left or [])
    for item in right or []:
        if item not in res:
            res.append(item)
    return res


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer that merges dictionaries."""
    res = dict(left or {})
    if right:
        res.update(right)
    return res


def merge_opportunities(
    left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer that deduplicates opportunities by id or title."""
    existing = list(left or [])
    seen = {str(o.get("id") or o.get("title")) for o in existing}
    for opp in right or []:
        key = str(opp.get("id") or opp.get("title"))
        if key not in seen:
            seen.add(key)
            existing.append(opp)
    return existing


class GrowthWorkflowState(TypedDict, total=False):
    """Authoritative typed state schema for the LangGraph growth execution pipeline."""

    # Tenant and Execution Identifiers
    merchant_id: str
    run_id: str
    workflow_id: Optional[str]
    mode: str
    objective: str
    window_days: int
    params: dict[str, Any]

    # Lease & Concurrency Control
    generation: int
    lease_owner: str
    current_step_index: int
    plan: list[tuple[str, dict[str, Any]]]

    # Multi-Agent Routing & Execution Telemetry
    selected_specialists: list[str]
    agents_run: Annotated[list[dict[str, Any]], add_items]
    resumed_steps: Annotated[list[dict[str, Any]], add_items]
    needs_reconciliation: Annotated[list[str], add_unique_strings]

    # Domain Findings, Opportunities & Actions
    opportunities: Annotated[list[dict[str, Any]], merge_opportunities]
    ranked_opportunities: list[dict[str, Any]]
    findings: Annotated[list[dict[str, Any]], add_items]
    actions_proposed: Annotated[list[dict[str, Any]], add_items]
    tool_records: Annotated[list[dict[str, Any]], add_items]

    # Shared In-Flight Cross-Agent Context
    shared_memory: Annotated[dict[str, Any], merge_dicts]

    # Error & Cancellation Boundaries
    errors: Annotated[list[str], add_items]
    status: str  # "running" | "completed" | "partial" | "failed" | "cancelled" | "needs_reconciliation"
    cancelled: bool
    cancelled_at_step: Optional[int]

    # Synthesis & Results
    totals: dict[str, int]
    debate_id: Optional[str]
    action_plan: Optional[dict[str, Any]]
    terminal_outcome: dict[str, Any]
