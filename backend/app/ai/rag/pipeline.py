"""
Agentic RAG pipeline.

This is the core of the Agentic RAG implementation.

It is NOT a simple query → vector search → LLM pipeline.

Flow:
    1. Agent receives goal.
    2. LLM selects the most useful retrieval tool (tool selection step).
    3. Tool is called, evidence is collected.
    4. LLM evaluates whether evidence is sufficient or another tool is needed.
    5. Steps 2–4 repeat up to MAX_RETRIEVAL_STEPS.
    6. Once "done" or limit reached, LLM performs final reasoning over all evidence.
    7. Structured GrowthAnalysisResult is validated and returned.

Bounded: MAX_RETRIEVAL_STEPS = 3 — no infinite loops.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from backend.app.ai.agents.state import AgentState
from backend.app.ai.agents.tools import AgentToolkit, ToolError
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.models import GrowthAnalysisResult
from backend.app.ai.llm.provider import LLMError, LLMValidationError
from backend.app.ai.prompts.growth import (
    GROWTH_ANALYSIS_SYSTEM,
    GROWTH_ANALYSIS_USER,
    TOOL_SELECTION_SYSTEM,
    TOOL_SELECTION_USER,
)
from backend.app.ai.rag.citations import is_sufficient, summarise_evidence
from backend.app.ai.rag.context import RetrievedContext

log = logging.getLogger(__name__)

MAX_RETRIEVAL_STEPS = 3


class AgenticRAGPipeline:
    """
    Bounded agentic retrieval loop followed by structured LLM synthesis.

    The LLM actively decides what information to retrieve next rather than
    receiving a single fixed query. This is the distinction between
    Agentic RAG and simple RAG.
    """

    def __init__(
        self,
        llm: BaseLLMProvider,
        toolkit: AgentToolkit,
    ) -> None:
        self._llm = llm
        self._toolkit = toolkit

    def run(self, goal: str, merchant_id: uuid.UUID) -> AgentState:
        """
        Execute the full agentic analysis loop.

        Returns an AgentState describing what happened and what was found.
        Never raises — all errors are captured in AgentState.status.
        """
        state = AgentState(goal=goal, merchant_id=str(merchant_id))
        log.info("Agentic RAG started. run_id=%s goal=%r", state.run_id, goal[:80])

        all_contexts: list[RetrievedContext] = []
        used_tool_calls: list[str] = []

        # ── Agentic retrieval loop ───────────────────────────────────────
        for step in range(MAX_RETRIEVAL_STEPS):
            state.retrieval_steps_used = step + 1

            # Ask LLM which tool to call next
            tool_decision = self._select_next_tool(
                goal=goal,
                step=step,
                all_contexts=all_contexts,
                used_tool_calls=used_tool_calls,
            )

            tool_name = tool_decision.get("tool_name", "done")
            tool_params = tool_decision.get("tool_params", {})
            reasoning = tool_decision.get("reasoning", "")

            log.info(
                "Step %d/%d: tool=%r reasoning=%r",
                step + 1, MAX_RETRIEVAL_STEPS, tool_name, reasoning[:100]
            )

            if tool_name in ("done", "insufficient"):
                log.info("Agent signalled '%s' at step %d", tool_name, step + 1)
                break

            # Execute the tool
            try:
                ctx, summary = self._toolkit.call(tool_name, tool_params)
            except ToolError as exc:
                log.warning("Tool %r failed: %s", tool_name, exc)
                state.record_tool_call(tool_name, tool_params, f"FAILED: {exc}", 0)
                continue

            all_contexts.append(ctx)
            state.add_evidence(ctx.items)
            state.record_tool_call(tool_name, tool_params, summary, len(ctx.items))
            used_tool_calls.append(f"{tool_name}({json.dumps(tool_params)[:80]})")

            log.info("Step %d: retrieved %d items. Total evidence: %d", step + 1, len(ctx.items), len(state.retrieved_evidence))

        # ── Evidence sufficiency check ───────────────────────────────────
        if not is_sufficient(all_contexts):
            summary = summarise_evidence(all_contexts)
            log.warning("Insufficient evidence after %d steps: %s", state.retrieval_steps_used, summary)
            state.mark_insufficient(summary or "Insufficient evidence retrieved.")
            return state

        # ── Final synthesis — LLM reasons over all collected evidence ────
        evidence_text = "\n\n---\n\n".join(
            ctx.format_for_prompt() for ctx in all_contexts if not ctx.is_empty
        )
        evidence_summary = summarise_evidence(all_contexts)

        user_prompt = GROWTH_ANALYSIS_USER.format(
            goal=goal,
            evidence_text=evidence_text,
        )

        try:
            result: GrowthAnalysisResult = self._llm.generate_structured(
                system_prompt=GROWTH_ANALYSIS_SYSTEM,
                user_prompt=user_prompt,
                schema=GrowthAnalysisResult,
                temperature=0.1,
            )
            log.info(
                "LLM synthesis complete. insights=%d insufficient=%s run_id=%s",
                len(result.insights), result.insufficient_evidence, state.run_id,
            )
        except LLMValidationError as exc:
            state.fail(f"LLM output validation failed: {exc}")
            return state
        except LLMError as exc:
            state.fail(f"LLM call failed: {exc}")
            return state

        if result.insufficient_evidence:
            state.mark_insufficient(result.evidence_summary or "LLM reported insufficient evidence.")
            return state

        # Serialise insights for state storage
        insights_dicts = [insight.model_dump() for insight in result.insights]
        state.complete(insights=insights_dicts, evidence_summary=evidence_summary)
        return state

    # ------------------------------------------------------------------ #
    # Tool selection via LLM
    # ------------------------------------------------------------------ #

    def _select_next_tool(
        self,
        *,
        goal: str,
        step: int,
        all_contexts: list[RetrievedContext],
        used_tool_calls: list[str],
    ) -> dict[str, Any]:
        """
        Ask the LLM to select the next tool to call.

        Returns a dict with keys: tool_name, tool_params, reasoning.
        Falls back to a sensible default on parse failure.
        """
        evidence_summary = summarise_evidence(all_contexts) if all_contexts else "None yet"
        used_str = "\n".join(f"  - {t}" for t in used_tool_calls) if used_tool_calls else "  None yet"

        user_prompt = TOOL_SELECTION_USER.format(
            goal=goal,
            step=step,
            max_steps=MAX_RETRIEVAL_STEPS,
            evidence_summary=evidence_summary,
            used_tools=used_str,
        )

        try:
            raw = self._llm.generate(
                system_prompt=TOOL_SELECTION_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=256,
            )
            # Extract JSON from response
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            decision = json.loads(raw)
            return decision
        except (json.JSONDecodeError, LLMError) as exc:
            log.warning("Tool selection parsing failed at step %d: %s. Using default.", step, exc)
            # Default: on first step use merchant context; otherwise search broadly
            if step == 0:
                return {"tool_name": "get_merchant_context", "tool_params": {}, "reasoning": "default fallback"}
            return {"tool_name": "done", "tool_params": {}, "reasoning": "parse error fallback"}
