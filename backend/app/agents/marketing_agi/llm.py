"""MarketingAGI LLM wiring — Groq-first reasoning layer.

The Marketing Agent reasons with Groq. This module is the SINGLE place
that decides how the agent's LLM is built:

  1. When GROQ_API_KEY is configured (backend .env, never the frontend),
     the agent uses Groq with the centrally configured GROQ_MODEL,
     reusing the existing ``build_llm_provider`` factory and the shared
     ``GroqProvider`` (OpenAI-compatible endpoint, timeout, bounded
     retries, structured JSON output). No second LLM abstraction.
  2. Otherwise it falls back to the generic LLM_PROVIDER / LLM_API_KEY /
     LLM_MODEL configuration (also via ``build_llm_provider``).
  3. When no key is configured at all it returns None: the agent still
     runs its bounded deterministic workflow honestly and marks the run
     degraded — it never fabricates LLM reasoning.

The API key never leaves the backend: this module is imported only by
backend code (routes, workers). There is no VITE_GROQ_API_KEY and no
frontend path to the key.
"""
from __future__ import annotations

import logging

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.core.config import get_settings

log = logging.getLogger(__name__)


def llm_identity() -> tuple[bool, str | None, str | None]:
    """Return (configured, provider, model) for the Marketing Agent.

    Groq is preferred whenever GROQ_API_KEY is set, regardless of the
    generic LLM_PROVIDER value (which may point at an unsupported
    provider); otherwise the generic LLM configuration applies.
    """
    settings = get_settings()
    if settings.GROQ_API_KEY:
        return True, "groq", settings.GROQ_MODEL
    if settings.LLM_API_KEY:
        return True, settings.LLM_PROVIDER, settings.LLM_MODEL
    return False, None, None


def build_marketing_llm() -> BaseLLMProvider | None:
    """Build the Marketing Agent's reasoning LLM, or None when unconfigured.

    Reuses the existing provider factory; never raises for a missing key
    (returns None) but lets genuine factory errors propagate so a
    misconfigured provider is visible instead of silently deterministic.
    """
    settings = get_settings()
    if settings.GROQ_API_KEY:
        from backend.app.ai.llm.provider import build_llm_provider

        return build_llm_provider(
            provider="groq",
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if settings.LLM_API_KEY:
        from backend.app.ai.llm.provider import build_llm_provider

        return build_llm_provider(
            provider=settings.LLM_PROVIDER,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    return None
