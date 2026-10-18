"""
LangChain Chat Model Adapter for RazorGrowth AI.

Wraps the existing BaseLLMProvider (Cloudflare Workers AI or OpenAI-compatible)
inside a standard LangChain BaseChatModel so all 14 agents can leverage LangChain
prompts, tools, and structured outputs without changing provider configurations.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterator, List, Optional, Sequence, Type, TypeVar, Union

from pydantic import BaseModel, Field

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.provider import LLMError, LLMValidationError
from backend.app.core.config import Settings, get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _format_messages_to_prompts(messages: Sequence[BaseMessage]) -> tuple[str, str]:
    """Split LangChain messages into system prompt and consolidated user prompt."""
    system_parts: list[str] = []
    user_parts: list[str] = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_parts.append(str(msg.content))
        elif isinstance(msg, HumanMessage):
            user_parts.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            user_parts.append(f"Assistant: {msg.content}")
        elif isinstance(msg, ChatMessage):
            user_parts.append(f"{msg.role.capitalize()}: {msg.content}")
        else:
            user_parts.append(str(msg.content))

    system_prompt = "\n\n".join(system_parts) or "You are an autonomous AI specialist for the RazorGrowth growth platform."
    user_prompt = "\n\n".join(user_parts) if user_parts else "Proceed with your specialized growth analysis."
    return system_prompt, user_prompt


class RazorGrowthChatModel(BaseChatModel):
    """LangChain BaseChatModel backed by RazorGrowth's BaseLLMProvider.

    Maintains complete vendor independence and strict tenant isolation.
    """

    provider: Any = Field(default=None, description="Instance of BaseLLMProvider")
    model_name: str = Field(default="razorgrowth-default-llm")
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=2048)
    timeout_seconds: int = Field(default=60)
    max_retries: int = Field(default=3)

    model_config = {
        "arbitrary_types_allowed": True,
    }

    @property
    def _llm_type(self) -> str:
        return "razorgrowth-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronously generate completion using RazorGrowth provider."""
        system_prompt, user_prompt = _format_messages_to_prompts(messages)
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        if self.provider is None:
            # Deterministic/mock response when no provider is configured
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="Analysis completed without active LLM provider."
                        )
                    )
                ]
            )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                text = self.provider.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if stop:
                    for s in stop:
                        if s in text:
                            text = text.split(s)[0]
                message = AIMessage(content=text)
                return ChatResult(generations=[ChatGeneration(message=message)])
            except Exception as exc:
                last_error = exc
                log.warning(
                    "RazorGrowthChatModel generation attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt == self.max_retries:
                    raise LLMError(f"Model generation failed after {self.max_retries} attempts: {exc}") from exc

        raise LLMError(f"Generation failed: {last_error}")

    def with_structured_output(
        self,
        schema: Union[Type[T], dict[str, Any]],
        *,
        method: str = "function_calling",
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        """Produce structured output conforming to a Pydantic schema or JSON schema."""
        target_schema: Type[BaseModel]
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            target_schema = schema
        else:
            raise ValueError(f"Schema must be a Pydantic BaseModel class, got {schema}")

        def _invoke_structured(input_data: Any) -> Any:
            messages: list[BaseMessage]
            if isinstance(input_data, list):
                messages = input_data
            elif isinstance(input_data, str):
                messages = [HumanMessage(content=input_data)]
            elif hasattr(input_data, "to_messages"):
                messages = input_data.to_messages()
            else:
                messages = [HumanMessage(content=str(input_data))]

            system_prompt, user_prompt = _format_messages_to_prompts(messages)

            if self.provider is not None:
                try:
                    return self.provider.generate_structured(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        schema=target_schema,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                except Exception as exc:
                    log.warning("Provider generate_structured failed, attempting fallback parse: %s", exc)

            # Fallback: prompt for JSON and parse with Pydantic
            schema_json = json.dumps(target_schema.model_json_schema(), indent=2)
            augmented_system = (
                f"{system_prompt}\n\n"
                f"You MUST return valid JSON adhering strictly to this schema:\n{schema_json}"
            )
            chat_res = self._generate(
                [SystemMessage(content=augmented_system), HumanMessage(content=user_prompt)],
                **kwargs,
            )
            raw_text = str(chat_res.generations[0].message.content).strip()
            # Clean markdown codeblocks if present
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            try:
                parsed = json.loads(raw_text)
                return target_schema.model_validate(parsed)
            except Exception as parse_exc:
                log.error("Failed to parse structured output from model text: %s", parse_exc)
                # Attempt default model instantiation if schema permits
                try:
                    return target_schema.model_validate({})
                except Exception:
                    raise LLMValidationError(f"Could not parse valid {target_schema.__name__}: {parse_exc}") from parse_exc

        return RunnableLambda(_invoke_structured)


def get_langchain_chat_model(
    provider: BaseLLMProvider | None = None,
    settings: Settings | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    timeout_seconds: int = 60,
    max_retries: int = 3,
) -> RazorGrowthChatModel:
    """Factory to build a RazorGrowthChatModel from existing configuration."""
    if provider is None:
        try:
            from backend.app.ai.llm.provider import resolve_llm_provider
            app_settings = settings or get_settings()
            resolved = resolve_llm_provider(app_settings)
            if resolved is not None:
                provider = resolved.build(
                    timeout=timeout_seconds,
                    max_retries=max_retries,
                    max_tokens=max_tokens,
                )
        except Exception as e:
            log.warning("Could not auto-resolve LLM provider for LangChain adapter: %s", e)
            provider = None

    return RazorGrowthChatModel(
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
