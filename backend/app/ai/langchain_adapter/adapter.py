"""
Unified LangChain Agent Adapter for all 14 RazorGrowth agents.

Provides standard execution, bounded retries, structured output enforcement,
tool binding, and lifecycle telemetry for any agent in the workforce.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.ai.langchain_adapter.model import (
    RazorGrowthChatModel,
    get_langchain_chat_model,
)
from backend.app.ai.langchain_adapter.prompts import (
    build_agent_chat_prompt,
    sanitize_context_data,
)
from backend.app.ai.langchain_adapter.tools import (
    CanonicalLangChainTool,
    get_agent_langchain_tools,
)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LangChainAgentAdapter:
    """Execution adapter connecting any BaseGrowthAgent to LangChain capabilities."""

    def __init__(
        self,
        agent_name: str,
        db: Session,
        merchant_id: uuid.UUID,
        chat_model: Optional[RazorGrowthChatModel] = None,
        llm: Any = None,
    ) -> None:
        self.agent_name = agent_name
        self.db = db
        self.merchant_id = merchant_id
        if chat_model is not None:
            self.model = chat_model
        elif llm is not None:
            self.model = RazorGrowthChatModel(provider=llm)
        else:
            self.model = get_langchain_chat_model()

        self._tools: list[CanonicalLangChainTool] | None = None

    @property
    def tools(self) -> list[CanonicalLangChainTool]:
        """Lazy-loaded list of authorized LangChain tools for this agent."""
        if self._tools is None:
            self._tools = get_agent_langchain_tools(
                self.agent_name,
                self.db,
                self.merchant_id,
            )
        return self._tools

    def invoke_tool(self, tool_id: str, **kwargs: Any) -> Any:
        """Execute an authorized tool via its CanonicalLangChainTool adapter."""
        for tool in self.tools:
            if tool.name == tool_id or getattr(tool.spec, "tool_id", None) == tool_id:
                return tool.invoke(kwargs)
        raise ValueError(f"Tool '{tool_id}' not available or not authorized for agent '{self.agent_name}'")

    def execute_structured_reasoning(
        self,
        system_instruction: str,
        user_instruction: str,
        schema: Type[T],
        context_vars: Optional[dict[str, Any]] = None,
        *,
        temperature: float = 0.1,
    ) -> tuple[T, int]:
        """Execute a LangChain structured reasoning step with validated Pydantic schema.

        Returns (validated_instance, elapsed_ms).
        """
        start_time = time.perf_counter()
        clean_vars = sanitize_context_data(context_vars or {})

        prompt = build_agent_chat_prompt(system_instruction, user_instruction)
        formatted_messages = prompt.format_messages(**clean_vars)

        structured_runner = self.model.with_structured_output(schema, temperature=temperature)
        res = structured_runner.invoke(formatted_messages)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return res, elapsed_ms

    def execute_text_reasoning(
        self,
        system_instruction: str,
        user_instruction: str,
        context_vars: Optional[dict[str, Any]] = None,
        *,
        temperature: float = 0.2,
    ) -> tuple[str, int]:
        """Execute free-form text reasoning via LangChain messages.

        Returns (response_text, elapsed_ms).
        """
        start_time = time.perf_counter()
        clean_vars = sanitize_context_data(context_vars or {})

        prompt = build_agent_chat_prompt(system_instruction, user_instruction)
        formatted_messages = prompt.format_messages(**clean_vars)

        chat_result = self.model.invoke(formatted_messages, temperature=temperature)
        text = str(chat_result.content).strip()

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return text, elapsed_ms
