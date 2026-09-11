"""Bound configuration for the MarketingAGI loop.

The autonomous loop MUST be bounded. These limits are enforced every
iteration; reaching any of them terminates the run with an explicit
status instead of looping forever.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopLimits:
    max_iterations: int = 14          # reasoning iterations per run
    max_tool_calls: int = 24         # total tool invocations per run
    max_retrieval_rounds: int = 3    # agentic-RAG retrieve→evaluate cycles
    max_llm_calls: int = 20          # model invocations per run
    llm_timeout_seconds: int = 60    # per-call LLM timeout
    run_timeout_seconds: int = 420   # hard wall-clock budget for a run
    max_retries_per_tool: int = 1    # retries after a tool failure
    max_audience_size: int = 5000    # safety ceiling for any audience
    min_audience_size: int = 1      # an audience of zero can never be prepared
    max_campaigns_per_run: int = 2  # concrete outputs per run


DEFAULT_LIMITS = LoopLimits()
