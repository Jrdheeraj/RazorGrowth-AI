"""Shared LangChain integration layer for RazorGrowth AI.

Provides provider-compatible LangChain chat models, structured output binding,
canonical tool adapters, and prompt templates across all 14 agents.
"""
from __future__ import annotations

from backend.app.ai.langchain_adapter.model import (
    RazorGrowthChatModel,
    get_langchain_chat_model,
)
from backend.app.ai.langchain_adapter.tools import (
    CanonicalLangChainTool,
    get_agent_langchain_tools,
    tool_spec_to_langchain_tool,
)
from backend.app.ai.langchain_adapter.adapter import (
    LangChainAgentAdapter,
)

__all__ = [
    "RazorGrowthChatModel",
    "get_langchain_chat_model",
    "CanonicalLangChainTool",
    "get_agent_langchain_tools",
    "tool_spec_to_langchain_tool",
    "LangChainAgentAdapter",
]
