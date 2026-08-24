"""
LLM provider implementations.

Providers:
  - OpenAIProvider — OpenAI chat completions
  - GroqProvider   — Groq chat completions (OpenAI-compatible endpoint)

Production-hardened (shared):
  - configurable timeout (LLM_REQUEST_TIMEOUT)
  - automatic retry on transient errors (LLM_MAX_RETRIES)
  - structured JSON output mode for generate_structured()
  - context-safe logging (API key never logged)
  - LLMError / LLMValidationError for all failure paths
"""
from __future__ import annotations

import json
import logging
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.ai.llm.base import BaseLLMProvider

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Transient error types that warrant a retry
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = ()  # populated lazily


class LLMError(Exception):
    """Raised when the LLM provider returns an error or times out."""


class LLMValidationError(Exception):
    """Raised when LLM output fails Pydantic schema validation."""


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient OpenAI errors (rate-limit, 5xx)."""
    try:
        import openai
        return isinstance(
            exc,
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.InternalServerError,
                openai.APIConnectionError,
            ),
        )
    except ImportError:
        return False


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI chat completions provider with production safeguards.

    - Timeout enforced via httpx_timeout on every request.
    - Retries up to `max_retries` times on transient errors with
      exponential back-off (1s, 2s).
    - JSON mode for generate_structured() — always valid JSON output.
    - API key is never logged.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 60,
        max_retries: int = 2,
        max_tokens: int = 2048,
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required. Run: pip install openai")

        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        client_kwargs: dict = {"api_key": api_key, "timeout": float(timeout)}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)
        log.info(
            "%s initialised. model=%s timeout=%ds max_retries=%d",
            type(self).__name__, model, timeout, max_retries,
        )

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        return self._call_with_retry(
            self._do_generate,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens or self._max_tokens,
            json_mode=False,
        )

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> T:
        json_instruction = (
            f"\n\nRespond ONLY with valid JSON that matches this schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )
        raw = self._call_with_retry(
            self._do_generate,
            system_prompt=system_prompt + json_instruction,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens or self._max_tokens,
            json_mode=True,
        )
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            log.error("LLM output failed schema validation: %s", exc)
            raise LLMValidationError(f"LLM output validation failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _do_generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        kwargs: dict = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        log.debug(
            "LLM call completed. model=%s tokens=%s",
            self._model,
            response.usage.total_tokens if response.usage else "?",
        )
        return content

    def _call_with_retry(self, fn, **kwargs) -> str:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and attempt < self._max_retries:
                    wait = 2 ** attempt  # 1s, 2s
                    log.warning(
                        "LLM transient error (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, self._max_retries + 1, wait, type(exc).__name__,
                    )
                    time.sleep(wait)
                else:
                    break
        log.error("LLM call failed after %d attempts: %s", self._max_retries + 1, type(last_exc).__name__)
        raise LLMError(f"LLM call failed: {type(last_exc).__name__}") from last_exc


class GroqProvider(OpenAIProvider):
    """
    Groq chat completions provider.

    Groq exposes an OpenAI-compatible /chat/completions endpoint, so this
    provider reuses the OpenAIProvider request/retry/validation logic and
    only retargets the SDK client at Groq's base URL. Timeout, retry with
    exponential back-off, max_tokens, JSON mode, and Pydantic validation
    behave identically. The API key is never logged.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        timeout: int = 60,
        max_retries: int = 2,
        max_tokens: int = 2048,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model or self.DEFAULT_MODEL,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            base_url=self.BASE_URL,
        )


def build_llm_provider(
    provider: str,
    api_key: str,
    model: str,
    timeout: int = 60,
    max_retries: int = 2,
    max_tokens: int = 2048,
) -> BaseLLMProvider:
    """
    Factory — construct the configured LLM provider.

    Supported: openai · groq
    """
    normalized = provider.lower()
    if normalized == "openai":
        return OpenAIProvider(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
        )
    if normalized == "groq":
        return GroqProvider(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}. Supported: openai, groq")
