"""LLM construction for the Product Agent.

Deliberately thin: it resolves the SAME Groq-first provider identity the
rest of the platform uses and delegates to the shared factory. There is no
Product Agent LLM client, no second SDK usage and no second retry policy.

``llm_identity`` is reused directly from the Marketing Agent module because
it is provider-agnostic: Groq wins when ``GROQ_API_KEY`` is configured,
otherwise the generic ``LLM_*`` settings are used, otherwise there is no
LLM and the agent runs its deterministic pipeline.
"""
from __future__ import annotations

import logging

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.provider import build_llm_provider
from backend.app.agents.marketing_agi.llm import llm_identity
from backend.app.core.config import get_settings

log = logging.getLogger(__name__)


def build_product_llm() -> BaseLLMProvider | None:
    """Build the shared LLM provider (Groq-first), or None when unconfigured.

    Returns None rather than raising when no key is configured: the agent
    then runs its deterministic pipeline and reports ``llm_degraded``, which
    is honest. A genuinely misconfigured provider still raises, so a bad
    setting is loud instead of silently deterministic.
    """
    settings = get_settings()
    if settings.GROQ_API_KEY:
        return build_llm_provider(
            provider="groq",
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if settings.LLM_API_KEY:
        return build_llm_provider(
            provider=settings.LLM_PROVIDER,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    return None


def build_embedding_provider_or_none():  # pragma: no cover - thin adapter
    """Embedding provider for research, or None when unavailable."""
    settings = get_settings()
    if not settings.LLM_API_KEY and not settings.GROQ_API_KEY:
        return None
    try:
        from backend.app.ai.embeddings.provider import (
            build_embedding_provider as _build,
        )

        return _build(
            provider=settings.EMBEDDING_PROVIDER,
            api_key=settings.LLM_API_KEY or settings.GROQ_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )
    except Exception:
        log.warning("Embedding provider unavailable; research falls back to tools")
        return None


__all__ = ["build_embedding_provider_or_none", "build_product_llm", "llm_identity"]