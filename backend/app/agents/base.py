"""
Base agent infrastructure — Phase 5 Features 1, 13, 14.

Every specialised agent:
  - has a clear responsibility (one per agent),
  - receives structured input (AgentContext),
  - returns structured output (AgentResult),
  - is restricted by the permission registry,
  - never raises past its boundary (execute() converts failures into
    structured failed results so one agent cannot crash the system),
  - records which internal tools it used and how long each layer took.
"""
from __future__ import annotations

import logging
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


@dataclass
class AgentResult:
    """Structured output produced by every agent run."""

    agent_name: str
    status: str = "completed"               # completed | failed | skipped
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

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class BaseGrowthAgent(ABC):
    """
    Abstract specialised agent.

    Subclasses implement `_run(ctx)` and MUST declare NAME + PERMISSIONS.
    All capability-gated helpers route through assert_permission so an
    agent physically cannot act outside its declared powers.
    """

    NAME: str = ""
    DESCRIPTION: str = ""
    PERMISSIONS: frozenset[str] = frozenset()
    TOOLS: tuple[str, ...] = ()

    # ── public entry point (never raises) ────────────────────────────────

    def execute(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        result = AgentResult(agent_name=self.NAME, tools_used=list(self.TOOLS))
        try:
            self._run(ctx, result)
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
        return result

    @abstractmethod
    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        """Do the agent's specialised work. Populate `result`."""

    # ── capability-gated helpers ─────────────────────────────────────────

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
        """
        self._require(PROPOSE_ACTION)
        t0 = time.perf_counter()
        action = action_service.create_action(
            db,
            merchant_id=merchant_id,
            action_type=action_type,
            input_payload=payload,
            requested_by=f"agent:{self.NAME}",
        )
        self._last_tool_ms = int((time.perf_counter() - t0) * 1000)
        return action

    @staticmethod
    def _timed(fn, *args, **kwargs):
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, int((time.perf_counter() - t0) * 1000)
