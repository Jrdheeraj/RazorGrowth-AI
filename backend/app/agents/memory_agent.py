"""
GrowthMemoryAgent — Phase 5 Features 10/11 wrapper.

Loads relevant memories into the orchestrator's shared context before the
deep agents run, and persists a run summary afterwards. Read/write are
strictly permission-gated; memory itself is strictly merchant-scoped.
"""
from __future__ import annotations

import logging
import uuid

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS
from backend.app.agents.permissions import READ_MEMORY as _READ
from backend.app.agents.permissions import WRITE_MEMORY as _WRITE
from backend.app.services.memory import GrowthMemoryService

log = logging.getLogger(__name__)


class GrowthMemoryAgent(BaseGrowthAgent):
    NAME = "GrowthMemoryAgent"
    DESCRIPTION = (
        "Remembers prior recommendations, outcomes, and preferences; "
        "recalls relevant history to ground new recommendations."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("memory_retrieve", "memory_record")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        self._require(_READ)
        memory = GrowthMemoryService(ctx.db, embedding_provider=ctx.embedding_provider)
        phase = str(ctx.params.get("phase", "load"))

        if phase == "load":
            hits = memory.retrieve(
                ctx.merchant_id,
                str(ctx.params.get("query", "strategy outcome recommendation")),
                k=int(ctx.params.get("k", 5)),
            )
            ctx.shared["memories"] = hits
            result.memories_written = 0
            result.output["memories_loaded"] = len(hits)
            return

        # persist phase
        self._require(_WRITE)
        summary = str(ctx.params.get("summary", "")).strip()
        if not summary:
            result.status = "skipped"
            result.output["note"] = "Nothing to remember."
            return
        row = memory.record(
            merchant_id=ctx.merchant_id,
            memory_type="recommendation",
            content=summary,
            source_type="agent_run",
            source_id=str(ctx.params.get("orchestrator_run_id", "")),
            importance=float(ctx.params.get("importance", 0.6)),
        )
        result.memories_written += 1
        result.output["memory_id"] = str(row.id)
