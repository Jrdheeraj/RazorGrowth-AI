"""
LLM provider interface.

All business logic must depend on BaseLLMProvider, never on a concrete
implementation. This keeps the vendor swappable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Abstract LLM provider. Concrete implementations live in provider.py."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """
        Generate a free-form text completion.

        Returns the raw assistant message string.
        Raises LLMError on failure.
        """

    @abstractmethod
    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> T:
        """
        Generate a structured response validated against `schema`.

        The LLM is instructed to return JSON; the response is parsed and
        validated. Raises LLMValidationError if output does not conform.
        Raises LLMError on provider failure.
        """
